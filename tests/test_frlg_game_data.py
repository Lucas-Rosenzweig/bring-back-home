from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.game_data import build_rfu_game_data, build_trainer_card
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant
from pokemon_trade.games.frlg.pokemon import FrlgTeam, Pk3


def pokemon(species: int) -> Pk3:
    header = bytearray(32)
    header[:4] = (1).to_bytes(4, "little")
    header[4:8] = (2).to_bytes(4, "little")
    growth = species.to_bytes(2, "little") + bytes(10)
    return Pk3.from_decrypted(bytes(header), growth + bytes(36))


class FrlgGameDataTest(unittest.TestCase):
    def test_builds_trade_game_data_and_card_from_typed_identity(self) -> None:
        identity = FrlgIdentity(0x1234, 0x5678, "EMU", FrlgVariant.LEAFGREEN)
        team = FrlgTeam((pokemon(25), pokemon(150)))

        game_data = build_rfu_game_data(identity)
        card = build_trainer_card(identity, team)

        self.assertEqual(len(game_data), 26)
        self.assertEqual(game_data[2:4], (0x1782).to_bytes(2, "little"))
        self.assertEqual(game_data[4:6], (0x1234).to_bytes(2, "little"))
        self.assertEqual(game_data[12], 0x84)
        self.assertEqual(len(card), 100)
        self.assertEqual(card[0x0E:0x10], (0x1234).to_bytes(2, "little"))
        self.assertEqual(card[0x38], 5)
        self.assertEqual(card[0x54:0x58], (25).to_bytes(2, "little") + (150).to_bytes(2, "little"))

    def test_advertises_trade_compatible_capabilities_for_both_frlg_versions(self) -> None:
        fire_red = FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED)
        leaf_green = FrlgIdentity(1, 2, "EMU", FrlgVariant.LEAFGREEN)

        self.assertEqual(build_rfu_game_data(fire_red)[2:4], (0x1382).to_bytes(2, "little"))
        self.assertEqual(build_rfu_game_data(leaf_green)[2:4], (0x1782).to_bytes(2, "little"))
