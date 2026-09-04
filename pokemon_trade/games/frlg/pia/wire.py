"""FRLG PIA application bridge from Reliable(10) to GBA emulator frames."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from statistics import median

from pokemon_trade.errors import MalformedDatagramError
from pokemon_trade.games.frlg.gba.frame import ParsedFrame, parse_frame
from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState, RfuCommand, RfuSlot
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.reliable import (
    RELIABLE_APP_DATA,
    RELIABLE_INITIALIZED,
    RELIABLE_MESSAGE_END,
    RELIABLE_MESSAGE_START,
    ReliableWireFrame,
)
from pokemon_trade.games.frlg.pia.session import PiaProtocol

RELIABLE_SEQUENCE_START = 0xFFF0
RELIABLE_ACK_BYTES = 16
RELIABLE_RTO_BASE_SECONDS = 0.033
RELIABLE_RTO_RTT_FACTOR = 1.4
RELIABLE_RTO_JITTER_FACTOR = 4.0
RELIABLE_RTO_CEILING_SECONDS = 0.670
RELIABLE_RTO_BOOTSTRAP_SECONDS = 0.200
RELIABLE_RTT_SAMPLE_COUNT = 7
RELIABLE_METADATA_FRAME = bytes.fromhex("4a002a005801004c656166477265656e5f65") + bytes(28)
# The FRLG host has a small reliable receive queue.  Keeping at most this
# many frames in flight prevents timestamp acknowledgements and RFU blocks
# from overrunning it on a userspace Wi-Fi link.
RELIABLE_MAX_INFLIGHT = 6
RELIABLE_MAX_ACK_INFLIGHT = 3
RELIABLE_MAX_PENDING_ACKS = 32
RELIABLE_PIA_BATCH_MAX = 9
RELIABLE_RETRANSMIT_BATCH_MAX = 2
RELIABLE_CONTROL_ACK_SECONDS = 2 / 59.7275


def _next_wire_sequence(value: int) -> int:
    """Advance FRLG's on-wire uint16 sequence space, including zero.

    The generic reliable helper reserves zero for its own synthetic ACK
    representation.  FRLG PIA does not: host data legitimately continues
    from ``0xffff`` at zero, so the game wire owns this distinct increment.
    """
    return 0 if value == 0xFFFF else value + 1


class FrlgPiaWire:
    """Owns only Reliable framing; transaction semantics remain above this layer."""

    def __init__(self, peer: PiaPeer, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.peer = peer
        self._clock = clock
        self._next_sequence = RELIABLE_SEQUENCE_START
        self._window_base = RELIABLE_SEQUENCE_START
        self._receive_next = RELIABLE_SEQUENCE_START
        self._receive_initialized = False
        self._peer_stream_initialized = False
        self._received_out_of_order: set[int] = set()
        self._unacknowledged: dict[int, tuple[ReliableWireFrame, float, bool]] = {}
        self._first_sent_at: dict[int, float] = {}
        self._retransmitted: set[int] = set()
        self._rtt_samples: deque[float] = deque(maxlen=RELIABLE_RTT_SAMPLE_COUNT)
        self._pending_data: deque[tuple[bytes, bool]] = deque()
        self._pending_ack_frames: deque[tuple[bytes, bool]] = deque()
        self._pending_pia_reliable: deque[tuple[int, bool]] = deque()
        self._control_ack_owed = False
        self._last_control_ack_at = 0.0
        self._initialized = False

    def receive_datagram(self, datagram: bytes, source_ip: str) -> tuple[ParsedFrame, ...]:
        frames: list[ParsedFrame] = []
        for message in self.peer.receive(datagram, source_ip):
            if message.protocol is not PiaProtocol.RELIABLE:
                continue
            reliable = ReliableWireFrame.parse(message.payload)
            if reliable.flags & RELIABLE_APP_DATA:
                if not self._peer_stream_initialized:
                    if not reliable.flags & RELIABLE_INITIALIZED:
                        # A host poll may overtake the stream-opening ACCEPT.
                        # Do not learn or acknowledge its later sequence: the
                        # host must retransmit it after Initialized establishes
                        # the receive base.
                        continue
                    self._peer_stream_initialized = True
                if not self._note_received(reliable.sequence):
                    self._queue_ack()
                    continue
                self._queue_ack()
                if reliable.flags & RELIABLE_INITIALIZED:
                    # Our opener carries title metadata, but the FRLG host's
                    # opener is also its emulator ``A``ccept control frame.
                    # Preserve metadata-only packets while forwarding a
                    # well-formed GBA frame to the RFU layer.
                    try:
                        frames.append(parse_frame(reliable.payload))
                    except MalformedDatagramError:
                        pass
                    continue
                frames.append(parse_frame(reliable.payload))
            else:
                self._apply_acknowledgement(reliable.payload)
        return tuple(frames)

    def begin(self, host_constant_id: bytes, local_variable_id: int) -> None:
        """Queue the initial PIA Session(join) request below Reliable."""
        self.peer.begin(host_constant_id, local_variable_id)

    @property
    def can_queue_child_slot(self) -> bool:
        """Whether one new emulator slot can enter Reliable immediately.

        The GBA bridge consumes at most one child ``T`` slot per VBlank.  A
        game-layer sender must therefore stop advancing while Reliable is
        full instead of accumulating slots which would later be released as a
        multi-slot burst.  Timestamp acknowledgements keep their separate
        priority queue and may claim the apparent free position first.
        """
        return not self._pending_data and len(self._unacknowledged) < RELIABLE_MAX_INFLIGHT

    @property
    def retransmission_timeout(self) -> float:
        """Current RTT-derived retransmission timeout in seconds."""
        if not self._rtt_samples:
            return RELIABLE_RTO_BOOTSTRAP_SECONDS
        middle = float(median(self._rtt_samples))
        deviation = sum(abs(sample - middle) for sample in self._rtt_samples) / len(
            self._rtt_samples
        )
        return min(
            RELIABLE_RTO_CEILING_SECONDS,
            RELIABLE_RTO_BASE_SECONDS
            + RELIABLE_RTO_RTT_FACTOR * middle
            + RELIABLE_RTO_JITTER_FACTOR * deviation,
        )

    def queue_frame(self, frame: bytes, *, initialized: bool = False) -> None:
        if initialized and not self._initialized:
            self._initialized = True
            self._pending_data.append((RELIABLE_METADATA_FRAME, True))
        pending = self._pending_ack_frames if _is_gba_timestamp_ack(frame) else self._pending_data
        if pending is self._pending_ack_frames and len(pending) >= RELIABLE_MAX_PENDING_ACKS:
            # A host retries its unacknowledged emulator timestamp.  Keeping
            # the newest bounded backlog is sufficient and leaves room for
            # the RFU NI/UNI frame that actually advances the game.
            pending.popleft()
        pending.append((bytes(frame), False))
        self._flush_pending_data()

    def discard_pending_child_idle_slots(
        self,
        *,
        discard_standby: bool = False,
    ) -> None:
        """Drop obsolete *unsent* child UNI slots before a phase boundary.

        Frames which already own a Reliable sequence must never be removed:
        doing so creates a permanent gap at the peer.  Only the local queue can
        be compacted safely; its entries have not yet appeared on the wire.
        """
        self._pending_data = deque(
            (frame, initialized)
            for frame, initialized in self._pending_data
            if not _is_obsolete_child_uni(frame, discard_standby=discard_standby)
        )
        self._flush_pending_data()

    def poll_retransmissions(self, now: float | None = None) -> None:
        """Requeue only the oldest elapsed gaps at each VBlank cadence.

        The peer buffers frames above a Reliable gap.  Resending the complete
        six-frame window on every timeout adds half-duplex contention without
        helping that gap close, so recovery is deliberately gap-targeted.
        """
        self._flush_pending_data()
        current = self._clock() if now is None else now
        queued = 0
        for sequence, (frame, sent_at, _is_ack) in tuple(self._unacknowledged.items()):
            if current - sent_at < self.retransmission_timeout:
                break
            self._unacknowledged[sequence] = (frame, current, _is_ack)
            self._retransmitted.add(sequence)
            self._pending_pia_reliable.append((sequence, _is_gba_timestamp_ack(frame.payload)))
            queued += 1
            if queued >= RELIABLE_RETRANSMIT_BATCH_MAX:
                break

    def _queue_data_frame(self, frame: bytes, *, initialized: bool = False, is_ack: bool = False) -> None:
        flags = RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END
        if initialized:
            flags |= RELIABLE_INITIALIZED
        reliable = ReliableWireFrame(flags, self._next_sequence, self._window_base, frame)
        self._pending_pia_reliable.append((self._next_sequence, is_ack))
        sent_at = self._clock()
        self._unacknowledged[self._next_sequence] = (reliable, sent_at, is_ack)
        self._first_sent_at[self._next_sequence] = sent_at
        self._next_sequence = _next_wire_sequence(self._next_sequence)

    def _flush_pending_data(self) -> None:
        """Move queued frames into a bounded window shared by K and RFU slots."""
        while len(self._unacknowledged) < RELIABLE_MAX_INFLIGHT:
            ack_inflight = sum(is_ack for _, _, is_ack in self._unacknowledged.values())
            if self._pending_ack_frames and ack_inflight < RELIABLE_MAX_ACK_INFLIGHT:
                frame, initialized = self._pending_ack_frames.popleft()
                self._queue_data_frame(frame, initialized=initialized, is_ack=True)
            elif self._pending_data:
                frame, initialized = self._pending_data.popleft()
                self._queue_data_frame(frame, initialized=initialized)
            else:
                return

    def drain_datagrams(self) -> tuple[bytes, ...]:
        # Session/Net replies must precede established application data.
        # Reliable K/data/control frames share a single ordered PIA batch just
        # like the console.  Keeping the cumulative ACK in a second datagram
        # doubles traffic during the RFU poll stream and can collapse this
        # half-duplex bridge before NI finishes.
        result = list(self.peer.drain())
        batch: list[bytes] = []
        message_flags: list[int] = []
        while self._pending_pia_reliable:
            sequence, _ = self._pending_pia_reliable.popleft()
            batch.append(self._unacknowledged[sequence][0].encode())
            message_flags.append(0)
            if len(batch) == RELIABLE_PIA_BATCH_MAX:
                result.append(
                    self.peer.encode_data_batch(
                        PiaProtocol.RELIABLE,
                        tuple(batch),
                        message_flags=tuple(message_flags),
                    )
                )
                batch.clear()
                message_flags.clear()
        # A Reliable bulk ACK is cumulative; sending one for every incoming
        # emulator timestamp floods this half-duplex link and starves actual
        # RFU blocks.  The console delays it by two VBlanks, then sends only
        # the newest cumulative state.
        now = self._clock()
        if self._control_ack_owed and now - self._last_control_ack_at >= RELIABLE_CONTROL_ACK_SECONDS:
            if len(batch) == RELIABLE_PIA_BATCH_MAX:
                result.append(
                    self.peer.encode_data_batch(
                        PiaProtocol.RELIABLE,
                        tuple(batch),
                        message_flags=tuple(message_flags),
                    )
                )
                batch.clear()
                message_flags.clear()
            batch.append(self._build_ack().encode())
            # Both the native follower and host mark Reliable control ACKs at
            # the PIA-message layer.  The marker enables selective-gap
            # handling; keeping the ACK last also prevents field inheritance
            # from affecting data messages.
            message_flags.append(0x40)
            self._control_ack_owed = False
            self._last_control_ack_at = now
        if batch:
            result.append(
                self.peer.encode_data_batch(
                    PiaProtocol.RELIABLE,
                    tuple(batch),
                    message_flags=tuple(message_flags),
                )
            )
        return tuple(result)

    def _note_received(self, sequence: int) -> bool:
        if not self._receive_initialized:
            # A lobby can keep its reliable counter across a follower retry.
            # Learn the first host data sequence instead of assuming that a
            # fresh follower always encounters the historical 0xfff0 origin.
            self._receive_next = sequence
            self._received_out_of_order.clear()
            self._receive_initialized = True
        if sequence == self._receive_next:
            self._receive_next = _next_wire_sequence(self._receive_next)
            while self._receive_next in self._received_out_of_order:
                self._received_out_of_order.remove(self._receive_next)
                self._receive_next = _next_wire_sequence(self._receive_next)
            return True
        if _is_newer(sequence, self._receive_next):
            if sequence in self._received_out_of_order:
                return False
            self._received_out_of_order.add(sequence)
            return True
        return False

    def _queue_ack(self) -> None:
        self._control_ack_owed = True

    def _build_ack(self) -> ReliableWireFrame:
        mask = bytearray(RELIABLE_ACK_BYTES)
        for sequence in self._received_out_of_order:
            offset = (sequence - self._receive_next - 1) & 0xFFFF
            if offset < RELIABLE_ACK_BYTES * 8:
                mask[offset >> 3] |= 1 << (offset & 7)
        payload = b"\0\x01" + self._receive_next.to_bytes(2, "big") + bytes(mask)
        # The FRLG host sends its reliable acknowledgements on the control
        # sequence (0xfff0); they must not consume a data sequence number.
        return ReliableWireFrame(0, RELIABLE_SEQUENCE_START, self._window_base, payload)

    def _apply_acknowledgement(self, payload: bytes) -> None:
        if len(payload) < 4 or payload[1] != 1:
            return
        next_expected = int.from_bytes(payload[2:4], "big")
        mask = int.from_bytes(payload[4 : 4 + RELIABLE_ACK_BYTES], "little")
        now = self._clock()
        for sequence in tuple(self._unacknowledged):
            acknowledged = _is_older(sequence, next_expected)
            if not acknowledged:
                offset = (sequence - next_expected - 1) & 0xFFFF
                acknowledged = offset < RELIABLE_ACK_BYTES * 8 and bool(mask & (1 << offset))
            if acknowledged:
                self._unacknowledged.pop(sequence)
                first_sent_at = self._first_sent_at.pop(sequence, None)
                if first_sent_at is not None and sequence not in self._retransmitted:
                    self._rtt_samples.append(max(0.0, now - first_sent_at))
                self._retransmitted.discard(sequence)
        self._advance_window_base()
        # Do not fill newly opened window slots yet.  The enclosing receive
        # path still has to decode the host GBA frame and enqueue its timestamp
        # K acknowledgement.  Filling here lets an old idle backlog occupy all
        # six slots first, starving the K the host needs before it emits its
        # next block fragment.  ``queue_frame`` or the end-of-ingest poll will
        # flush after those priority acknowledgements have been discovered.

    def _advance_window_base(self) -> None:
        while self._window_base not in self._unacknowledged and self._window_base != self._next_sequence:
            self._window_base = _next_wire_sequence(self._window_base)


def _is_newer(candidate: int, reference: int) -> bool:
    return candidate != reference and 0 < ((candidate - reference) & 0xFFFF) < 0x8000


def _is_older(candidate: int, reference: int) -> bool:
    return candidate != reference and 0 < ((reference - candidate) & 0xFFFF) < 0x8000


def _is_gba_timestamp_ack(frame: bytes) -> bool:
    return len(frame) >= 2 and frame[:2] == b"WK"


def _is_obsolete_child_uni(frame: bytes, *, discard_standby: bool) -> bool:
    if len(frame) < 28 or frame[:2] != b"WT":
        return False
    slot_size = frame[9]
    if slot_size < 16 or len(frame) < 12 + slot_size:
        return False
    try:
        llsf = ChildLlsf.parse(frame[12:14])
        slot = RfuSlot.parse(frame[14:28])
    except Exception:
        return False
    if llsf.state is not LlsfState.UNI:
        return False
    return slot.words[0] == 0 or (
        discard_standby and slot.command is RfuCommand.READY_EXIT_STANDBY
    )
