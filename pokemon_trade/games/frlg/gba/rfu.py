"""FRLG RFU child UNI/NI link-layer slots and command words."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from pokemon_trade.errors import MalformedDatagramError

SLOT_SIZE = 14


class LlsfState(IntEnum):
    NULL = 0
    NI_START = 1
    NI = 2
    NI_END = 3
    UNI = 4


class RfuCommand(IntEnum):
    IDLE = 0x0000
    READY_CLOSE_LINK = 0x5F00
    READY_EXIT_STANDBY = 0x6600
    SEND_PLAYER_IDS = 0x7700
    SEND_BLOCK_INIT = 0x8800
    SEND_BLOCK = 0x8900
    SEND_BLOCK_REQUEST = 0xA100
    SEND_HELD_KEYS = 0xBE00
    DISCONNECT = 0xED00


@dataclass(frozen=True, slots=True)
class ChildLlsf:
    state: LlsfState
    n: int = 0
    phase: int = 0
    acknowledge: bool = False
    size: int = 0

    def encode(self) -> bytes:
        if not 0 <= self.n <= 3 or not 0 <= self.phase <= 3 or not 0 <= self.size <= 31:
            raise ValueError("invalid child LLSF fields")
        value = (int(self.state) << 10) | (int(self.acknowledge) << 9) | (self.n << 7) | (self.phase << 5) | self.size
        return value.to_bytes(2, "little")

    @classmethod
    def parse(cls, data: bytes) -> ChildLlsf:
        if len(data) < 2:
            raise MalformedDatagramError("truncated child LLSF")
        value = int.from_bytes(data[:2], "little")
        try:
            state = LlsfState((value >> 10) & 0xF)
        except ValueError as error:
            raise MalformedDatagramError("invalid child LLSF state") from error
        return cls(state, (value >> 7) & 3, (value >> 5) & 3, bool((value >> 9) & 1), value & 0x1F)


@dataclass(frozen=True, slots=True)
class ParentLlsf:
    state: LlsfState
    n: int
    phase: int
    acknowledge: bool
    size: int

    @classmethod
    def parse(cls, data: bytes) -> ParentLlsf:
        if len(data) < 3:
            raise MalformedDatagramError("truncated parent LLSF")
        value = int.from_bytes(data[:3], "little")
        try:
            state = LlsfState((value >> 14) & 0xF)
        except ValueError as error:
            raise MalformedDatagramError("invalid parent LLSF state") from error
        return cls(state, (value >> 11) & 3, (value >> 9) & 3, bool((value >> 13) & 1), value & 0x7F)


@dataclass(frozen=True, slots=True)
class RfuSlot:
    words: tuple[int, int, int, int, int, int, int]

    def encode(self) -> bytes:
        return b"".join(word.to_bytes(2, "little") for word in self.words)

    @property
    def command(self) -> RfuCommand | None:
        try:
            return RfuCommand(self.words[0] & 0xFF00)
        except ValueError:
            return None

    @property
    def fragment_index(self) -> int:
        return self.words[0] & 0x1F

    @property
    def request_type(self) -> int:
        """Host block-request selector carried in word 1, not word 0."""
        if self.command is not RfuCommand.SEND_BLOCK_REQUEST:
            raise ValueError("only SEND_BLOCK_REQUEST slots have a request type")
        return self.words[1]

    @classmethod
    def parse(cls, data: bytes) -> RfuSlot:
        if len(data) != SLOT_SIZE:
            raise MalformedDatagramError("RFU command slot must contain exactly 14 bytes")
        words = [
            int.from_bytes(data[offset : offset + 2], "little")
            for offset in range(0, SLOT_SIZE, 2)
        ]
        return cls((words[0], words[1], words[2], words[3], words[4], words[5], words[6]))

    @classmethod
    def idle(cls) -> RfuSlot:
        return cls((0, 0, 0, 0, 0, 0, 0))

    @classmethod
    def block_init(cls, fragment_count: int, owner: int = 1) -> RfuSlot:
        return cls((RfuCommand.SEND_BLOCK_INIT, fragment_count & 0xFFFF, (owner & 0x7F) | 0x80, 0, 0, 0, 0))

    @classmethod
    def block_fragment(cls, index: int, data: bytes) -> RfuSlot:
        if not 0 <= index < 32:
            raise ValueError("RFU block fragment index must fit in five bits")
        padded = bytes(data[:12]).ljust(12, b"\0")
        words = [
            int.from_bytes(padded[offset : offset + 2], "little")
            for offset in range(0, 12, 2)
        ]
        return cls((int(RfuCommand.SEND_BLOCK) | index, words[0], words[1], words[2], words[3], words[4], words[5]))


class RfuSlotBuilder:
    """Applies the child rolling command tag; idle slots do not advance it."""

    def __init__(self) -> None:
        self.tag = 0

    def build(self, slot: RfuSlot) -> RfuSlot:
        if slot.words[0] == 0:
            return slot
        words = list(slot.words)
        words[0] = (words[0] | (self.tag << 5)) & 0xFFFF
        self.tag = (self.tag + 1) & 7
        return RfuSlot((words[0], words[1], words[2], words[3], words[4], words[5], words[6]))


def uni_slot(slot: RfuSlot) -> bytes:
    return ChildLlsf(LlsfState.UNI, size=SLOT_SIZE).encode() + slot.encode()
