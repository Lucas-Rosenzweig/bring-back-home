from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.identity import (
    FrlgIdentity,
    FrlgVariant,
    LinkPlayerRecord,
    decode_gen3_text,
    encode_gen3_text,
)


class FrlgIdentityTest(unittest.TestCase):
    def test_gen3_text_and_link_player_block(self) -> None:
        self.assertEqual(decode_gen3_text(encode_gen3_text("Red-1", 8)), "Red-1")
        identity = FrlgIdentity(0x1234, 0x5678, "Red", FrlgVariant.FIRERED)
        record = LinkPlayerRecord(identity)
        self.assertEqual(len(record.encode()), 28)
        self.assertEqual(len(record.block()), 60)
        self.assertEqual(record.block()[:14], b"GameFreak inc.")
