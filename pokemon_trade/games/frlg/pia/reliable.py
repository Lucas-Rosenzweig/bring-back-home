"""Deterministic sliding-window reliable transport state for FRLG PIA."""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.errors import MalformedDatagramError, TradeTimeoutError

MAX_SEQUENCE = 0xFFFF
ACK_WINDOW = 32
RELIABLE_HEADER_SIZE = 8
RELIABLE_APP_DATA = 0x01
RELIABLE_MESSAGE_START = 0x02
RELIABLE_MESSAGE_END = 0x04
RELIABLE_INITIALIZED = 0x08


@dataclass(frozen=True, slots=True)
class ReliableWireFrame:
    """The FRLG PIA Reliable(10) envelope around an emulator payload."""

    flags: int
    sequence: int
    window_base: int
    payload: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.flags <= 0xFF or not 0 <= self.sequence <= MAX_SEQUENCE or not 0 <= self.window_base <= MAX_SEQUENCE:
            raise ValueError("invalid FRLG reliable wire header")
        if len(self.payload) > 0xFFFF:
            raise ValueError("FRLG reliable payload exceeds uint16 length")
        object.__setattr__(self, "payload", bytes(self.payload))

    def encode(self) -> bytes:
        return b"".join(
            (
                bytes((self.flags,)),
                len(self.payload).to_bytes(2, "big"),
                self.sequence.to_bytes(2, "big"),
                self.window_base.to_bytes(2, "big"),
                b"\0",  # recipient bitmap count: unicast
                self.payload,
            )
        )

    @classmethod
    def parse(cls, data: bytes) -> ReliableWireFrame:
        if len(data) < RELIABLE_HEADER_SIZE:
            raise MalformedDatagramError("truncated FRLG reliable frame")
        size = int.from_bytes(data[1:3], "big")
        recipients = data[7]
        if recipients != 0:
            raise MalformedDatagramError("multicast FRLG reliable frames are unsupported")
        if len(data) != RELIABLE_HEADER_SIZE + size:
            raise MalformedDatagramError("FRLG reliable payload length mismatch")
        return cls(data[0], int.from_bytes(data[3:5], "big"), int.from_bytes(data[5:7], "big"), data[8:])


def next_sequence(value: int) -> int:
    return 1 if value >= MAX_SEQUENCE else value + 1


def is_newer(candidate: int, reference: int) -> bool:
    """Compare non-zero uint16 sequence numbers with wrap-around."""
    if candidate == reference:
        return False
    return 0 < ((candidate - reference) & MAX_SEQUENCE) < 0x8000


@dataclass(frozen=True, slots=True)
class ReliableFrame:
    sequence: int
    acknowledge: int
    acknowledge_bits: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.sequence <= MAX_SEQUENCE or not 0 <= self.acknowledge <= MAX_SEQUENCE:
            raise ValueError("reliable sequence values must fit in uint16")
        if not 0 <= self.acknowledge_bits <= 0xFFFFFFFF:
            raise ValueError("reliable acknowledgement bitmap must fit in uint32")
        object.__setattr__(self, "payload", bytes(self.payload))


@dataclass(slots=True)
class _Pending:
    payload: bytes
    attempts: int = 0
    sent_at: float | None = None


class ReliableChannel:
    """Windowed ordered delivery with bounded retransmission.

    The caller maps ``ReliableFrame`` values to the FRLG protocol's wire
    messages.  Keeping framing separate makes packet-loss tests deterministic.
    """

    def __init__(self, *, rto_seconds: float = 0.35, max_attempts: int = 8) -> None:
        if rto_seconds <= 0 or max_attempts < 1:
            raise ValueError("RTO must be positive and max_attempts at least one")
        self.rto_seconds = rto_seconds
        self.max_attempts = max_attempts
        self._next_send = 1
        self._next_receive = 1
        self._latest_receive = 0
        self._receive_bits = 0
        self._pending: dict[int, _Pending] = {}
        self._out_of_order: dict[int, bytes] = {}

    def queue(self, payload: bytes) -> int:
        if not payload:
            raise ValueError("reliable payload must not be empty")
        sequence = self._next_send
        self._next_send = next_sequence(sequence)
        self._pending[sequence] = _Pending(bytes(payload))
        return sequence

    def poll(self, now: float) -> tuple[ReliableFrame, ...]:
        frames: list[ReliableFrame] = []
        for sequence, pending in tuple(self._pending.items()):
            if pending.sent_at is not None and now - pending.sent_at < self.rto_seconds:
                continue
            if pending.attempts >= self.max_attempts:
                raise TradeTimeoutError(f"reliable frame {sequence} exceeded retransmission limit")
            pending.attempts += 1
            pending.sent_at = now
            frames.append(self._frame(sequence, pending.payload))
        return tuple(frames)

    def acknowledge_only(self) -> ReliableFrame:
        return self._frame(0, b"")

    def receive(self, frame: ReliableFrame) -> tuple[bytes, ...]:
        self._apply_acknowledgements(frame.acknowledge, frame.acknowledge_bits)
        if frame.sequence == 0:
            return ()
        self._record_received(frame.sequence)
        if frame.sequence == self._next_receive:
            delivered = [frame.payload]
            self._next_receive = next_sequence(self._next_receive)
            while self._next_receive in self._out_of_order:
                delivered.append(self._out_of_order.pop(self._next_receive))
                self._next_receive = next_sequence(self._next_receive)
            return tuple(delivered)
        if is_newer(frame.sequence, self._next_receive):
            self._out_of_order.setdefault(frame.sequence, frame.payload)
        return ()

    @property
    def pending_sequences(self) -> tuple[int, ...]:
        return tuple(self._pending)

    def _frame(self, sequence: int, payload: bytes) -> ReliableFrame:
        return ReliableFrame(sequence, self._latest_receive, self._receive_bits, payload)

    def _apply_acknowledgements(self, acknowledge: int, bits: int) -> None:
        if acknowledge:
            self._pending.pop(acknowledge, None)
        for offset in range(ACK_WINDOW):
            if bits & (1 << offset):
                sequence = (acknowledge - offset - 1) & MAX_SEQUENCE
                if sequence:
                    self._pending.pop(sequence, None)

    def _record_received(self, sequence: int) -> None:
        if self._latest_receive == 0:
            self._latest_receive = sequence
            self._receive_bits = 0
            return
        if is_newer(sequence, self._latest_receive):
            distance = (sequence - self._latest_receive) & MAX_SEQUENCE
            if distance > ACK_WINDOW:
                self._receive_bits = 0
            else:
                self._receive_bits = ((self._receive_bits << distance) | (1 << (distance - 1))) & 0xFFFFFFFF
            self._latest_receive = sequence
        else:
            distance = (self._latest_receive - sequence) & MAX_SEQUENCE
            if 1 <= distance <= ACK_WINDOW:
                self._receive_bits |= 1 << (distance - 1)
