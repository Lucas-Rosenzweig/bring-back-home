"""Codec for the Switch GBA-emulator envelope used by FRLG RFU traffic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from pokemon_trade.errors import MalformedDatagramError

MARKER = 0x57


class FrameType(IntEnum):
    ACCEPT = ord("A")
    CONNECT = ord("C")
    DISCONNECT = ord("D")
    GROUP = ord("G")
    ACKNOWLEDGE = ord("K")
    SLOT = ord("T")


def _padded_size(size: int) -> int:
    return (size + 3) & ~3


@dataclass(frozen=True, slots=True)
class ControlFrame:
    frame_type: FrameType
    body: bytes

    def encode(self) -> bytes:
        return bytes((MARKER, self.frame_type)) + len(self.body).to_bytes(2, "little") + self.body


@dataclass(frozen=True, slots=True)
class ChildSlotFrame:
    """A follower-to-host RFU slot at a single emulator timestamp."""

    timestamp: int
    slot: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.timestamp <= 0xFFFFFFFF or len(self.slot) > 0xFF:
            raise ValueError("invalid child emulator timestamp or slot length")
        object.__setattr__(self, "slot", bytes(self.slot))

    def encode(self) -> bytes:
        padded = self.slot + bytes(_padded_size(len(self.slot)) - len(self.slot))
        body = self.timestamp.to_bytes(4, "little") + bytes((0, len(self.slot), 0, 0)) + padded
        return ControlFrame(FrameType.SLOT, body).encode()


@dataclass(frozen=True, slots=True)
class HostSlotFrame:
    """A host-to-follower RFU slot; its slot-length byte is one byte earlier."""

    timestamp: int
    slot: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.timestamp <= 0xFFFFFFFF or len(self.slot) > 0xFF:
            raise ValueError("invalid host emulator timestamp or slot length")
        object.__setattr__(self, "slot", bytes(self.slot))


@dataclass(frozen=True, slots=True)
class AcknowledgeFrame:
    sequence: int
    message_index: int
    acknowledged_timestamp: int

    def encode(self) -> bytes:
        if any(not 0 <= value <= 0xFFFFFFFF for value in (self.sequence, self.message_index, self.acknowledged_timestamp)):
            raise ValueError("emulator acknowledgement values must fit in uint32")
        body = b"".join(value.to_bytes(4, "little") for value in (self.sequence, self.message_index, self.acknowledged_timestamp))
        return ControlFrame(FrameType.ACKNOWLEDGE, body).encode()


ParsedFrame = ControlFrame | HostSlotFrame | AcknowledgeFrame


def parse_frame(payload: bytes) -> ParsedFrame:
    if len(payload) < 4 or payload[0] != MARKER:
        raise MalformedDatagramError("invalid GBA emulator frame marker")
    try:
        frame_type = FrameType(payload[1])
    except ValueError as error:
        raise MalformedDatagramError(f"unsupported GBA emulator frame type: 0x{payload[1]:02X}") from error
    body_size = int.from_bytes(payload[2:4], "little")
    if len(payload) != 4 + body_size:
        raise MalformedDatagramError("GBA emulator frame length mismatch")
    body = payload[4:]
    if frame_type is FrameType.SLOT:
        return _parse_host_slot(body)
    if frame_type is FrameType.ACKNOWLEDGE:
        if len(body) != 12:
            raise MalformedDatagramError("GBA acknowledgement body must contain 12 bytes")
        return AcknowledgeFrame(
            int.from_bytes(body[0:4], "little"),
            int.from_bytes(body[4:8], "little"),
            int.from_bytes(body[8:12], "little"),
        )
    return ControlFrame(frame_type, body)


def _parse_host_slot(body: bytes) -> HostSlotFrame:
    if len(body) < 5:
        raise MalformedDatagramError("truncated host GBA slot frame")
    timestamp = int.from_bytes(body[0:4], "little")
    slot_size = body[4]
    if slot_size <= 1:
        # The parent emits a compact idle heartbeat as only timestamp +
        # slot-size.  It still needs a `K` acknowledgement, but has no RFU
        # payload to feed into the link state machine.
        return HostSlotFrame(timestamp, b"")
    if len(body) < 8 + slot_size:
        raise MalformedDatagramError("host GBA slot frame has inconsistent slot length")
    slot = body[8 : 8 + slot_size]
    # The parent frame may carry its RFU slot unpadded or retain adapter-owned
    # bytes after it.  The slot length is authoritative; accepting that suffix
    # avoids desynchronising from a valid host control/idle frame.
    return HostSlotFrame(timestamp, slot)


class HostTimestampAcker:
    """Generate exactly one acknowledgement per newly observed host timestamp."""

    def __init__(self) -> None:
        self._seen: set[int] = set()
        self._sequence = 1

    def acknowledge(self, frame: HostSlotFrame, message_index: int) -> AcknowledgeFrame | None:
        if frame.timestamp in self._seen:
            return None
        self._seen.add(frame.timestamp)
        acknowledgement = AcknowledgeFrame(self._sequence, message_index, frame.timestamp)
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return acknowledgement
