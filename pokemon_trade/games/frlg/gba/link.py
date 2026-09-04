"""Follower-side bridge between GBA emulator frames and RFU slots."""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.gba.frame import (
    AcknowledgeFrame,
    ChildSlotFrame,
    ControlFrame,
    FrameType,
    HostSlotFrame,
    HostTimestampAcker,
    ParsedFrame,
)
from pokemon_trade.games.frlg.gba.ni import NiSender, acknowledgement_for_parent_ni
from pokemon_trade.games.frlg.gba.rfu import LlsfState, ParentLlsf, RfuSlot, RfuSlotBuilder, uni_slot

CHILD_TIMESTAMP_SEED = 0x362E


@dataclass(frozen=True, slots=True)
class RfuInbound:
    accepted: bool = False
    host_poll_received: bool = False
    host_uni_entered: bool = False
    slots: tuple[RfuSlot, ...] = ()
    positional_slots: tuple[tuple[int, RfuSlot], ...] = ()


class RfuFollowerLink:
    """Owns follower timestamps, K ACKs, NI exchange, and UNI slot decoding."""

    def __init__(self, connect_id: bytes, game_data: bytes) -> None:
        if len(connect_id) != 2:
            raise ValueError("FRLG RFU connect ID must contain two bytes")
        self.connect_id = bytes(connect_id)
        self._ni = NiSender(bytes(game_data))
        self._accepted = False
        self._host_uni_seen = False
        self._last_host_ni_ack: tuple[LlsfState, int, int] | None = None
        # The emulator's child counter is a session-local, non-zero timeline,
        # not an RFU sequence number.  Starting at the observed seed avoids a
        # synthetic zero-era timestamp during the C/NI transition.
        self._timestamp = CHILD_TIMESTAMP_SEED
        self._acker = HostTimestampAcker()
        self._slots = RfuSlotBuilder()
        self._outbound: list[bytes] = []

    def start(self) -> bytes:
        return ControlFrame(FrameType.CONNECT, self.connect_id).encode()

    def tick(self) -> None:
        """Emit one child NI tile per VBlank after host acceptance."""
        self._send_next_ni()

    def receive(self, frame: ParsedFrame, message_index: int) -> RfuInbound:
        if isinstance(frame, ControlFrame) and frame.frame_type is FrameType.ACCEPT:
            if len(frame.body) < 4 or frame.body[2:4] != self.connect_id:
                raise ProtocolStateError("host GBA accept does not echo the follower connect ID")
            self._accepted = True
            return RfuInbound(accepted=True)
        if not isinstance(frame, HostSlotFrame):
            return RfuInbound()
        acknowledgement = self._acker.acknowledge(frame, message_index)
        if acknowledgement is not None:
            self._outbound.append(acknowledgement.encode())
        if len(frame.slot) <= 1:
            return RfuInbound(host_poll_received=True)
        parent = ParentLlsf.parse(frame.slot)
        payload = frame.slot[3:]
        if parent.state is LlsfState.UNI:
            host_uni_entered = not self._host_uni_seen
            self._host_uni_seen = True
            slots = tuple(
                RfuSlot.parse(payload[offset : offset + 14])
                for offset in range(0, len(payload) - 13, 14)
            )
            return RfuInbound(
                host_poll_received=True,
                host_uni_entered=host_uni_entered,
                slots=slots,
                positional_slots=tuple(enumerate(slots)),
            )
        if not parent.acknowledge:
            self._acknowledge_host_ni(parent)
        return RfuInbound(host_poll_received=True)

    def queue_uni(self, slot: RfuSlot) -> None:
        if not self._accepted:
            raise ProtocolStateError("cannot send FRLG UNI data before host acceptance")
        self._queue_child_slot(uni_slot(self._slots.build(slot)))

    @property
    def ready_for_uni(self) -> bool:
        """True only once both RFU peers have completed NI and host entered UNI."""
        return self._accepted and self._ni.done and self._host_uni_seen

    def drain(self) -> tuple[bytes, ...]:
        result = tuple(self._outbound)
        self._outbound.clear()
        return result

    def _queue_child_slot(self, slot: bytes) -> None:
        self._outbound.append(ChildSlotFrame(self._timestamp, slot).encode())
        self._timestamp = (self._timestamp + 1) & 0xFFFFFFFF

    def _send_next_ni(self) -> None:
        if not self._accepted or self._ni.done:
            return
        slot = self._ni.next_slot()
        if slot is None:
            return
        self._queue_child_slot(slot)

    def _acknowledge_host_ni(self, parent: ParentLlsf) -> None:
        """Mirror each distinct host NI sub-frame exactly once.

        Parent ``ack=1`` confirms our outbound NI; parent ``ack=0`` instead
        carries the host's own NI transfer.  Its acknowledgement is a distinct
        child slot and must not be confused with either the GBA timestamp ACK
        or the follower's next game-data tile.
        """
        key = (parent.state, parent.n, parent.phase)
        if key == self._last_host_ni_ack:
            return
        acknowledgement_slot = acknowledgement_for_parent_ni(*key)
        if acknowledgement_slot is None:
            return
        self._last_host_ni_ack = key
        self._queue_child_slot(acknowledgement_slot)
