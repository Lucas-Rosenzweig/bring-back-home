"""Idempotent RFU block fragmentation and reassembly."""

from __future__ import annotations

from dataclasses import dataclass, field

from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.gba.rfu import RfuCommand, RfuSlot

FRAGMENT_SIZE = 12


def fragment_count(length: int) -> int:
    return max(1, (length + FRAGMENT_SIZE - 1) // FRAGMENT_SIZE)


@dataclass(slots=True)
class BlockAssembly:
    count: int = 0
    owner: int | None = None
    fragments: dict[int, bytes] = field(default_factory=dict)

    def start(self, count: int, owner: int) -> None:
        if not 1 <= count <= 32:
            raise ProtocolStateError("RFU block fragment count must be one through 32")
        if count != self.count or self.owner != owner:
            self.count, self.owner, self.fragments = count, owner, {}

    def add(self, index: int, data: bytes) -> bytes | None:
        if not self.count or not 0 <= index < self.count:
            return None
        self.fragments.setdefault(index, bytes(data[:FRAGMENT_SIZE]).ljust(FRAGMENT_SIZE, b"\0"))
        if len(self.fragments) == self.count:
            result = b"".join(self.fragments[index] for index in range(self.count))
            self.fragments = {}
            self.count = 0
            return result
        return None


class BlockReceiver:
    def __init__(self, peer_count: int = 5) -> None:
        self._peers = [BlockAssembly() for _ in range(peer_count)]

    def receive(self, peer: int, slot: RfuSlot) -> bytes | None:
        if not 0 <= peer < len(self._peers):
            raise ProtocolStateError("RFU peer index is outside the configured mesh")
        assembly = self._peers[peer]
        if slot.command is RfuCommand.SEND_BLOCK_INIT:
            assembly.start(slot.words[1], slot.words[2] & 0x7F)
        elif slot.command is RfuCommand.SEND_BLOCK:
            return assembly.add(slot.fragment_index, slot.encode()[2:14])
        return None

    def missing(self, peer: int, expected_count: int) -> tuple[int, ...]:
        """Return fragment indices not yet reflected by one RFU peer."""
        if not 0 <= peer < len(self._peers):
            raise ProtocolStateError("RFU peer index is outside the configured mesh")
        assembly = self._peers[peer]
        if assembly.count != expected_count:
            return tuple(range(expected_count))
        return tuple(index for index in range(expected_count) if index not in assembly.fragments)


class BlockSender:
    """One-way child block stream paced by the caller's RFU VBlank tick.

    PIA supplies ordered retransmission below this layer, so fragments need not
    be mirrored by RFU. The RFU receiver still needs four INIT VBlanks to arm
    before it will accept fragment zero, matching the live Switch cadence.
    """

    def __init__(self, data: bytes, *, owner: int = 1) -> None:
        if not 0 <= owner <= 0x7F:
            raise ValueError("RFU block owner must fit in seven bits")
        self.data = bytes(data)
        self.owner = owner
        self.count = fragment_count(len(self.data))
        if self.count > 32:
            raise ValueError("RFU block exceeds the 32-fragment protocol limit")
        self._index = -1
        self._init_emits = 0

    @property
    def done(self) -> bool:
        return self._index >= self.count

    def next_slot(self) -> RfuSlot | None:
        """Return the next INIT/fragment slot, or ``None`` once exhausted."""
        if self.done:
            return None
        if self._index == -1:
            self._init_emits += 1
            # The FRLG sender repeats INIT for four VBlanks even on the PIA
            # bridge. Reliable ordering does not substitute for the
            # receiver's RFU-side arming interval.
            if self._init_emits <= 4:
                return RfuSlot.block_init(self.count, self.owner)
            self._index = 0
        index = self._index
        self._index += 1
        start = index * FRAGMENT_SIZE
        return RfuSlot.block_fragment(index, self.data[start : start + FRAGMENT_SIZE])
