"""Small deterministic FRLG leader peer for full-stack client tests.

This peer intentionally does not reuse the follower driver.  It builds host
PIA/GBA/RFU frames from the documented wire layouts and reacts to the child's
observable commands, which makes it useful for catching orchestration defects
between otherwise unit-tested layers.
"""

from __future__ import annotations

from collections import deque

import trio

from pokemon_trade.games.frlg.gba.blocks import BlockReceiver, fragment_count
from pokemon_trade.games.frlg.gba.frame import ControlFrame, FrameType
from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState, RfuCommand, RfuSlot
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant, LinkPlayerRecord
from pokemon_trade.games.frlg.live import FRLG_PIA_GAME_KEY
from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16, encrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import (
    PiaMessage,
    PiaPacketV16,
    decode_messages_v16,
    encode_messages_v16,
)
from pokemon_trade.games.frlg.pia.peer import FRLG_PIA_COMPRESS_MIN
from pokemon_trade.games.frlg.pia.reliable import (
    RELIABLE_APP_DATA,
    RELIABLE_INITIALIZED,
    RELIABLE_MESSAGE_END,
    RELIABLE_MESSAGE_START,
    ReliableWireFrame,
)
from pokemon_trade.games.frlg.pia.session import PiaProtocol
from pokemon_trade.games.frlg.pia.wire import RELIABLE_ACK_BYTES, RELIABLE_SEQUENCE_START
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.games.frlg.trade.wire import (
    LINKCMD_BOTH_CANCEL_TRADE,
    LINKCMD_CONFIRM_FINISH_TRADE,
    LINKCMD_INIT_BLOCK,
    LINKCMD_READY_FINISH_TRADE,
    LINKCMD_READY_TO_TRADE,
    LINKCMD_REQUEST_CANCEL,
    LINKCMD_SET_MONS_TO_TRADE,
    LINKCMD_START_TRADE,
    is_link_player_block,
    link_command,
    parse_link_command,
)
from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext

HOST_VARIABLE_ID = 0x2222
LOCAL_VARIABLE_ID = 0x1111
HOST_IP = "169.254.1.1"
LOCAL_IP = "169.254.1.2"
PIA_PORT = 12345


def synthetic_session() -> SessionContext:
    return SessionContext(
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        0x01006FA0233F8000,
        22287,
        88,
        "synthetic0",
        ParticipantAddress(LOCAL_IP, "02:00:00:00:00:02"),
        ParticipantAddress(HOST_IP, "02:00:00:00:00:01"),
        "169.254.1.255",
    )


def _next_sequence(value: int) -> int:
    return 0 if value == 0xFFFF else value + 1


def _older(candidate: int, reference: int) -> bool:
    return candidate != reference and 0 < ((reference - candidate) & 0xFFFF) < 0x8000


def _parent_llsf(
    state: LlsfState,
    *,
    n: int = 0,
    phase: int = 0,
    acknowledge: bool = False,
    payload: bytes = b"",
) -> bytes:
    value = (
        (int(state) << 14)
        | (int(acknowledge) << 13)
        | ((n & 3) << 11)
        | ((phase & 3) << 9)
        | len(payload)
    )
    return value.to_bytes(3, "little") + payload


class SyntheticFrlgHostTransport:
    """In-memory datagram transport backed by a deterministic leader FSM."""

    def __init__(self, received: Pk3) -> None:
        self.session = synthetic_session()
        self._received = received
        self._incoming: deque[Datagram] = deque()
        self._incoming_ready = trio.Event()
        self._closed = False
        self._host_packet_id = 1
        self._host_timestamp = 1
        self._host_sequence = RELIABLE_SEQUENCE_START
        self._host_stream_open = False
        self._client_next: int | None = None
        self._client_out_of_order: set[int] = set()
        self._net_sent = False
        self._session_sent = False
        self._rtt_sent = False
        self._host_ni: deque[bytes] = deque()
        self._scheduled_gba: deque[bytes] = deque()
        self._child_blocks = BlockReceiver(peer_count=1)
        self._child_block_count: int | None = None
        self._link_player_received = False
        self._trainer_card_received = False
        self._barrier_observations: dict[int, int] = {}
        self._menu_scheduled = False
        self._save_scheduled = False
        self._menu_requests: deque[int] = deque()
        self._menu_request_inflight: int | None = None
        self._save_barrier_counts: deque[int] = deque()
        self._cancel_exit_counts: deque[int] = deque()
        self._cancel_close_sent = False

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        if self._closed:
            raise RuntimeError("synthetic FRLG host transport is closed")
        if destination != (HOST_IP, PIA_PORT):
            raise AssertionError(f"unexpected synthetic destination: {destination}")
        packet = PiaPacketV16.parse(payload)
        application, _ = decrypt_frlg_v16(
            packet,
            self.session.ssid,
            FRLG_PIA_GAME_KEY,
            LOCAL_IP,
        )
        immediate_gba: list[bytes] = []
        # A phase response scheduled while consuming this datagram must not be
        # returned alongside the final child fragment.  The follower clears
        # its BlockSender on the next VBlank, matching the leader's observed
        # one-packet turn-around on hardware.
        scheduled_before = len(self._scheduled_gba)
        client_slot_received = False
        received_reliable_data = False
        for message in decode_messages_v16(application):
            protocol = PiaProtocol(message.protocol_type)
            if protocol is PiaProtocol.SESSION:
                self._on_session(message.payload)
            elif protocol is PiaProtocol.NET:
                self._on_net(message.payload)
            elif protocol is PiaProtocol.RELIABLE:
                reliable = ReliableWireFrame.parse(message.payload)
                if reliable.flags & RELIABLE_APP_DATA:
                    received_reliable_data = True
                    if self._note_client_sequence(reliable.sequence):
                        client_slot_received = client_slot_received or reliable.payload[:2] == b"WT"
                        immediate_gba.extend(self._on_client_gba(reliable.payload))
        if received_reliable_data:
            frames = [self._host_ack()]
            if immediate_gba:
                frames.extend(self._host_app(frame) for frame in immediate_gba)
            elif (
                scheduled_before
                and (client_slot_received or not self._link_player_received)
                and self._scheduled_gba
            ):
                frames.append(self._host_app(self._scheduled_gba.popleft()))
            elif client_slot_received:
                # The RFU leader continuously polls its child.  Even when no
                # game command is scheduled, answering a child T with the
                # next idle parent T grants exactly one subsequent child-slot
                # credit and prevents the synthetic transport from modelling
                # an impossible free-running follower.
                frames.append(self._host_app(self._host_uni(RfuSlot.idle())))
            self._push_protocol(
                PiaProtocol.RELIABLE,
                tuple(frame.encode() for frame in frames),
            )

    async def receive(self) -> Datagram:
        while not self._incoming:
            if self._closed:
                raise RuntimeError("synthetic FRLG host transport is closed")
            ready = self._incoming_ready
            await ready.wait()
        return self._incoming.popleft()

    async def aclose(self) -> None:
        self._closed = True
        self._incoming_ready.set()

    def _on_session(self, payload: bytes) -> None:
        if not self._net_sent and payload[:1] == b"\0":
            self._net_sent = True
            body = (
                (1).to_bytes(4, "big")
                + HOST_VARIABLE_ID.to_bytes(2, "big")
                + bytes.fromhex(self.session.host.mac_address.replace(":", ""))
            )
            self._push_protocol(
                PiaProtocol.NET,
                (b"\0\x11" + len(body).to_bytes(2, "big") + body,),
            )
        elif payload[:1] == b"\x06" and not self._rtt_sent:
            self._rtt_sent = True
            self._push_protocol(PiaProtocol.RTT, (bytes(21),))

    def _on_net(self, payload: bytes) -> None:
        if len(payload) >= 2 and payload[1] == 0x12 and not self._session_sent:
            self._session_sent = True
            self._push_protocol(PiaProtocol.SESSION, (b"\x05\x01",))

    def _on_client_gba(self, payload: bytes) -> tuple[bytes, ...]:
        if payload[:2] == b"WC" and len(payload) >= 6:
            return (
                ControlFrame(FrameType.ACCEPT, b"\0\0" + payload[4:6]).encode(),
                self._host_slot(b""),
            )
        if payload[:2] == b"WD":
            return ()
        if payload[:2] != b"WT" or len(payload) < 12:
            return ()
        slot_size = payload[9]
        raw_slot = payload[12 : 12 + slot_size]
        if len(raw_slot) < 2:
            return ()
        llsf = ChildLlsf.parse(raw_slot)
        if llsf.state is not LlsfState.UNI:
            return self._on_child_ni(llsf)
        if len(raw_slot) < 16:
            return ()
        slot = RfuSlot.parse(raw_slot[2:16])
        responses = self._on_child_uni(slot)
        if (
            not responses
            and slot.command in {RfuCommand.SEND_BLOCK_INIT, RfuCommand.SEND_BLOCK}
        ):
            # A real leader rebroadcasts the follower's slot at mesh position
            # one.  The client must wait for this echo to complete before it
            # starts the next child-initiated standby barrier.
            return (self._host_uni(RfuSlot.idle(), child_echo=slot),)
        return responses

    def _on_child_ni(self, llsf: ChildLlsf) -> tuple[bytes, ...]:
        if llsf.acknowledge:
            if not self._host_ni:
                return ()
            outgoing = self._host_ni.popleft()
            if llsf.state is LlsfState.NI_END:
                self._schedule_initial_uni()
            return (self._host_slot(outgoing),)
        if llsf.state in {LlsfState.NI_START, LlsfState.NI, LlsfState.NI_END}:
            acknowledgement = _parent_llsf(
                llsf.state,
                n=llsf.n,
                phase=llsf.phase,
                acknowledge=True,
            )
            return (self._host_slot(acknowledgement),)
        if llsf.state is LlsfState.NULL:
            self._host_ni.extend(
                (
                    _parent_llsf(LlsfState.NI_START, n=2, payload=b"\0\0"),
                    _parent_llsf(LlsfState.NI, n=1, payload=b"\x05"),
                    _parent_llsf(LlsfState.NI_END),
                    _parent_llsf(LlsfState.NULL, n=1),
                )
            )
            first = _parent_llsf(LlsfState.NI_START, n=1, payload=b"\x01\x0c\0\x01\0")
            return (self._host_slot(first),)
        return ()

    def _on_child_uni(self, slot: RfuSlot) -> tuple[bytes, ...]:
        if slot.command is RfuCommand.SEND_BLOCK_INIT:
            self._child_block_count = slot.words[1]
        completed = self._child_blocks.receive(0, slot)
        if completed is not None:
            if self._child_block_count is None:
                raise AssertionError("child block completed without init")
            count = self._child_block_count
            self._child_block_count = None
            self._on_child_block(count, completed)
        if slot.command is RfuCommand.READY_EXIT_STANDBY:
            count = slot.words[1]
            seen = self._barrier_observations.get(count, 0) + 1
            self._barrier_observations[count] = seen
            if self._save_barrier_counts and count == self._save_barrier_counts[0]:
                response = self._host_uni(
                    RfuSlot((RfuCommand.READY_EXIT_STANDBY, count, 0, 0, 0, 0, 0))
                )
                if seen >= 2:
                    self._save_barrier_counts.popleft()
                    if not self._save_barrier_counts:
                        self._begin_menu_exchange()
                return (response,)
            if self._cancel_exit_counts and count == self._cancel_exit_counts[0]:
                response = self._host_uni(
                    RfuSlot((RfuCommand.READY_EXIT_STANDBY, count, 0, 0, 0, 0, 0))
                )
                if seen >= 2:
                    self._cancel_exit_counts.popleft()
                    if not self._cancel_exit_counts:
                        self._cancel_close_sent = True
                        self._scheduled_gba.append(
                            self._host_uni(
                                RfuSlot((RfuCommand.READY_CLOSE_LINK, 13, 0, 0, 0, 0, 0))
                            )
                        )
                return (response,)
            if seen == 1 and count <= 4:
                return (self._host_uni(RfuSlot((RfuCommand.READY_EXIT_STANDBY, count, 0, 0, 0, 0, 0))),)
            if count == 0 and seen == 2:
                request = RfuSlot((RfuCommand.SEND_BLOCK_REQUEST, 2, 0, 0, 0, 0, 0))
                return (self._host_uni(request),)
            if count == 1 and seen == 2:
                held = RfuSlot((RfuCommand.SEND_HELD_KEYS, 0x0116, 0, 0, 0, 0, 0))
                self._schedule_menu_data()
                return (self._host_uni(held),)
        if slot.command is RfuCommand.READY_CLOSE_LINK and self._cancel_close_sent:
            self._cancel_close_sent = False
            return (ControlFrame(FrameType.DISCONNECT, b"").encode(),)
        return ()

    def _on_child_block(self, count: int, data: bytes) -> None:
        if not self._link_player_received and count == 17 and is_link_player_block(data):
            self._link_player_received = True
            host_identity = FrlgIdentity(10, 20, "HOST", FrlgVariant.FIRERED)
            self._schedule_host_block(LinkPlayerRecord(host_identity).block().ljust(200, b"\0"))
            return
        if not self._trainer_card_received and count == 9:
            self._trainer_card_received = True
            return
        if self._menu_request_inflight is not None:
            self._menu_request_inflight = None
            if self._menu_requests:
                self._schedule_next_menu_request()
            else:
                self._schedule_host_menu_blocks()
            return
        if count != 2:
            return
        command, _ = parse_link_command(data)
        if command == LINKCMD_READY_TO_TRADE:
            self._schedule_host_block(link_command(LINKCMD_SET_MONS_TO_TRADE, 0))
        elif command == LINKCMD_INIT_BLOCK:
            self._schedule_host_block(link_command(LINKCMD_START_TRADE))
        elif command == LINKCMD_READY_FINISH_TRADE:
            self._schedule_host_block(link_command(LINKCMD_CONFIRM_FINISH_TRADE))
            self._schedule_save_data()
        elif command == LINKCMD_REQUEST_CANCEL:
            self._cancel_exit_counts.extend((11, 12))
            self._schedule_host_block(link_command(LINKCMD_BOTH_CANCEL_TRADE))

    def _schedule_initial_uni(self) -> None:
        self._scheduled_gba.extend(
            (
                self._host_uni(RfuSlot.idle()),
                self._host_uni(RfuSlot((RfuCommand.SEND_PLAYER_IDS, 2, 1, 0, 0, 0, 0))),
                self._host_uni(RfuSlot((RfuCommand.SEND_BLOCK_REQUEST, 0, 0, 0, 0, 0, 0))),
            )
        )

    def _schedule_menu_data(self) -> None:
        if self._menu_scheduled:
            return
        self._menu_scheduled = True
        self._begin_menu_exchange()

    def _begin_menu_exchange(self) -> None:
        self._menu_requests.extend((0, 0, 0, 3, 4))
        self._schedule_next_menu_request()

    def _schedule_next_menu_request(self) -> None:
        request_type = self._menu_requests.popleft()
        self._menu_request_inflight = request_type
        request = RfuSlot((RfuCommand.SEND_BLOCK_REQUEST, request_type, 0, 0, 0, 0, 0))
        self._scheduled_gba.append(self._host_uni(request))

    def _schedule_host_menu_blocks(self) -> None:
        party = self._received.party_bytes + bytes(500)
        for offset in range(0, 600, 200):
            self._schedule_host_block(party[offset : offset + 200])
        self._schedule_host_block(bytes(40))

    def _schedule_save_data(self) -> None:
        if self._save_scheduled:
            return
        self._save_scheduled = True
        # A compact but structurally faithful save chain: the production host
        # continues through later counts, while two echoed rounds are enough
        # for the full-stack fixture to prove child initiation and pacing.
        self._save_barrier_counts.extend(range(5, 11))

    def _schedule_host_block(self, data: bytes) -> None:
        count = fragment_count(len(data))
        for _ in range(4):
            self._scheduled_gba.append(self._host_uni(RfuSlot.block_init(count, owner=0)))
        for index in range(count):
            start = index * 12
            self._scheduled_gba.append(
                self._host_uni(RfuSlot.block_fragment(index, data[start : start + 12]))
            )

    def _host_uni(self, slot: RfuSlot, *, child_echo: RfuSlot | None = None) -> bytes:
        echoed = child_echo or RfuSlot.idle()
        slots = slot.encode() + echoed.encode() + RfuSlot.idle().encode() * 3
        return self._host_slot(_parent_llsf(LlsfState.UNI, payload=slots))

    def _host_slot(self, slot: bytes) -> bytes:
        body = self._host_timestamp.to_bytes(4, "little") + bytes((len(slot), 0, 0, 0)) + slot
        self._host_timestamp += 1
        return ControlFrame(FrameType.SLOT, body).encode()

    def _host_app(self, payload: bytes) -> ReliableWireFrame:
        flags = RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END
        if not self._host_stream_open:
            flags |= RELIABLE_INITIALIZED
            self._host_stream_open = True
        frame = ReliableWireFrame(flags, self._host_sequence, RELIABLE_SEQUENCE_START, payload)
        self._host_sequence = _next_sequence(self._host_sequence)
        return frame

    def _host_ack(self) -> ReliableWireFrame:
        assert self._client_next is not None
        mask = bytearray(RELIABLE_ACK_BYTES)
        for sequence in self._client_out_of_order:
            offset = (sequence - self._client_next - 1) & 0xFFFF
            if offset < RELIABLE_ACK_BYTES * 8:
                mask[offset >> 3] |= 1 << (offset & 7)
        payload = b"\0\x01" + self._client_next.to_bytes(2, "big") + bytes(mask)
        return ReliableWireFrame(0, RELIABLE_SEQUENCE_START, RELIABLE_SEQUENCE_START, payload)

    def _note_client_sequence(self, sequence: int) -> bool:
        if self._client_next is None:
            self._client_next = sequence
        if sequence == self._client_next:
            self._client_next = _next_sequence(self._client_next)
            while self._client_next in self._client_out_of_order:
                self._client_out_of_order.remove(self._client_next)
                self._client_next = _next_sequence(self._client_next)
            return True
        if _older(sequence, self._client_next):
            return False
        if sequence in self._client_out_of_order:
            return False
        self._client_out_of_order.add(sequence)
        return True

    def _push_protocol(self, protocol: PiaProtocol, payloads: tuple[bytes, ...]) -> None:
        messages = tuple(PiaMessage(0, int(protocol), 0, 0, payload) for payload in payloads)
        application = encode_messages_v16(messages)
        packet_id = self._host_packet_id
        self._host_packet_id = _next_sequence(packet_id)
        packet = encrypt_frlg_v16(
            ssid=self.session.ssid,
            game_key=FRLG_PIA_GAME_KEY,
            source_ip=HOST_IP,
            destination_variable_id=LOCAL_VARIABLE_ID,
            source_variable_id=HOST_VARIABLE_ID,
            packet_id=packet_id,
            nonce=packet_id.to_bytes(8, "big"),
            application=application,
            footer=LOCAL_VARIABLE_ID.to_bytes(2, "big"),
            compressed=len(application) >= FRLG_PIA_COMPRESS_MIN,
        )
        self._push(packet.encode())

    def _push(self, payload: bytes) -> None:
        self._incoming.append(
            Datagram(
                payload,
                (HOST_IP, PIA_PORT),
                (LOCAL_IP, PIA_PORT),
                trio.current_time(),
            )
        )
        ready = self._incoming_ready
        self._incoming_ready = trio.Event()
        ready.set()
