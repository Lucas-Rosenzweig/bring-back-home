"""FRLG trade-room block layouts and follower-only LINKCMD values.

This is intentionally below the semantic trade engine and above RFU slots. It
contains no socket, PIA or radio state, so synthetic block traces can exercise
the same party staging used by a live driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.pokemon import PARTY_SIZE, FrlgTeam, Pk3

PARTY_MEMBERS = 6
PARTY_BLOCK_SIZE = 200
PARTY_WIRE_SIZE = PARTY_MEMBERS * PARTY_SIZE
PARTY_BLOCK_COUNT = PARTY_WIRE_SIZE // PARTY_BLOCK_SIZE

BLOCK_REQUEST_200 = frozenset({0, 1})
BLOCK_REQUEST_TRAINER_CARD = 2
BLOCK_REQUEST_MAIL = 3
BLOCK_REQUEST_RIBBONS = 4

LINKCMD_READY_TO_TRADE = 0xAABB
LINKCMD_SET_MONS_TO_TRADE = 0xDDDD
LINKCMD_INIT_BLOCK = 0xBBBB
LINKCMD_START_TRADE = 0xCCDD
LINKCMD_READY_FINISH_TRADE = 0xABCD
LINKCMD_CONFIRM_FINISH_TRADE = 0xDCBA
LINKCMD_REQUEST_CANCEL = 0xEEAA
LINKCMD_READY_CANCEL_TRADE = 0xBBCC
LINKCMD_PLAYER_CANCEL_TRADE = 0xDDEE
LINKCMD_BOTH_CANCEL_TRADE = 0xEEBB
LINKCMD_PARTNER_CANCEL_TRADE = 0xEECC

LINK_PLAYER_MAGIC = b"GameFreak inc.\0\0"


def link_command(command: int, cursor: int = 0) -> bytes:
    """Encode the 20-byte block used for a follower LINKCMD action."""
    if not 0 <= command <= 0xFFFF or not 0 <= cursor <= 0xFFFF:
        raise ValueError("FRLG LINKCMD fields must fit in uint16")
    return command.to_bytes(2, "little") + cursor.to_bytes(2, "little") + bytes(16)


def parse_link_command(data: bytes) -> tuple[int, int]:
    if len(data) < 4:
        raise ProtocolStateError("truncated FRLG LINKCMD block")
    return int.from_bytes(data[:2], "little"), int.from_bytes(data[2:4], "little")


def is_link_player_block(data: bytes) -> bool:
    return len(data) >= 60 and data[:16] == LINK_PLAYER_MAGIC and data[44:60] == LINK_PLAYER_MAGIC


@dataclass(slots=True)
class FrlgPartyBuffer:
    """Accumulate the host's three padded party blocks and select valid entries."""

    _blocks: list[bytes] = field(default_factory=list)

    def add(self, data: bytes) -> bool:
        if len(data) < PARTY_BLOCK_SIZE:
            raise ProtocolStateError("truncated FRLG party block")
        if self.complete:
            raise ProtocolStateError("received a fourth FRLG party block before a new round")
        self._blocks.append(bytes(data[:PARTY_BLOCK_SIZE]))
        return self.complete

    @property
    def complete(self) -> bool:
        return len(self._blocks) == PARTY_BLOCK_COUNT

    def selected(self, cursor: int) -> Pk3:
        if not self.complete:
            raise ProtocolStateError("host party is incomplete at trade confirmation")
        index = cursor % PARTY_MEMBERS
        start = index * PARTY_SIZE
        return Pk3.parse(b"".join(self._blocks)[start : start + PARTY_SIZE])

    def reset(self) -> None:
        self._blocks.clear()


class FrlgFollowerBlockPlan:
    """Serve host-pulled follower blocks without inventing leader traffic."""

    def __init__(
        self,
        team: FrlgTeam,
        *,
        link_player_block: bytes,
        trainer_card: bytes,
    ) -> None:
        if len(link_player_block) != 60 or not is_link_player_block(link_player_block):
            raise ValueError("FRLG LinkPlayer block must be a 60-byte GameFreak record")
        if len(trainer_card) != 100:
            raise ValueError("FRLG trainer card must contain 100 bytes")
        self._team = team
        self._link_player_block = bytes(link_player_block)
        self._trainer_card = bytes(trainer_card)
        self._link_player_sent = False
        self._party_index = 0

    @property
    def team(self) -> FrlgTeam:
        return self._team

    @property
    def link_player_sent(self) -> bool:
        return self._link_player_sent

    def replace(self, slot: int, received: Pk3) -> None:
        self._team = self._team.replace(slot, received)

    def begin_next_menu(self) -> None:
        self._party_index = 0

    def block_for_request(self, request_type: int) -> bytes:
        if request_type in BLOCK_REQUEST_200:
            if not self._link_player_sent:
                self._link_player_sent = True
                return self._link_player_block.ljust(PARTY_BLOCK_SIZE, b"\0")
            blocks = self._party_blocks()
            if self._party_index >= len(blocks):
                raise ProtocolStateError("host requested too many FRLG party blocks")
            result = blocks[self._party_index]
            self._party_index += 1
            return result
        if request_type == BLOCK_REQUEST_TRAINER_CARD:
            return self._trainer_card
        if request_type == BLOCK_REQUEST_MAIL:
            return bytes(220)
        if request_type == BLOCK_REQUEST_RIBBONS:
            return bytes(40)
        raise ProtocolStateError(f"unsupported FRLG block request type: {request_type}")

    def _party_blocks(self) -> tuple[bytes, bytes, bytes]:
        data = b"".join(member.party_bytes for member in self._team.members)
        data = data.ljust(PARTY_WIRE_SIZE, b"\0")
        return tuple(
            data[index : index + PARTY_BLOCK_SIZE]
            for index in range(0, PARTY_WIRE_SIZE, PARTY_BLOCK_SIZE)
        )  # type: ignore[return-value]
