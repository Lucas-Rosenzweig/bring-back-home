from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant, LinkPlayerRecord
from pokemon_trade.games.frlg.pokemon import FrlgTeam, Pk3
from pokemon_trade.games.frlg.trade.wire import (
    FrlgFollowerBlockPlan,
    FrlgPartyBuffer,
    LINKCMD_READY_TO_TRADE,
    link_command,
    parse_link_command,
)


def pokemon(value: int) -> Pk3:
    header = bytearray(32)
    header[:4] = value.to_bytes(4, "little")
    header[4:8] = (7).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes([value]) * 48)


class FrlgTradeWireTest(unittest.TestCase):
    def test_follower_serves_link_player_then_current_party_per_menu(self) -> None:
        team = FrlgTeam((pokemon(1), pokemon(2)))
        link_player = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED)).block()
        plan = FrlgFollowerBlockPlan(team, link_player_block=link_player, trainer_card=bytes(100))

        self.assertEqual(plan.block_for_request(0)[:60], link_player)
        first_party = plan.block_for_request(1)
        self.assertEqual(first_party[:100], pokemon(1).party_bytes)
        plan.block_for_request(1)
        plan.block_for_request(1)
        plan.replace(0, pokemon(3))
        plan.begin_next_menu()
        self.assertEqual(plan.block_for_request(1)[:100], pokemon(3).party_bytes)

    def test_host_party_selection_is_only_available_after_three_blocks(self) -> None:
        received = pokemon(5)
        party = bytes(100) + received.party_bytes + bytes(400)
        buffer = FrlgPartyBuffer()
        self.assertFalse(buffer.add(party[:200]))
        self.assertFalse(buffer.add(party[200:400]))
        self.assertTrue(buffer.add(party[400:600]))
        self.assertEqual(buffer.selected(1).party_bytes, received.party_bytes)

    def test_link_commands_are_fixed_width_little_endian(self) -> None:
        block = link_command(LINKCMD_READY_TO_TRADE, 4)
        self.assertEqual(len(block), 20)
        self.assertEqual(parse_link_command(block), (LINKCMD_READY_TO_TRADE, 4))
