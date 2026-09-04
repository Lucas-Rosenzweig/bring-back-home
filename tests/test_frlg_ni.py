from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.gba.ni import NiSender, acknowledgement_for_parent_ni
from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState


class NiTest(unittest.TestCase):
    def test_sends_header_payload_end_and_null(self) -> None:
        sender = NiSender(bytes(range(26)))
        slots = []
        while (slot := sender.next_slot()) is not None:
            slots.append(slot)
        headers = [ChildLlsf.parse(slot) for slot in slots]
        self.assertEqual([header.state for header in headers], [LlsfState.NI_START, LlsfState.NI, LlsfState.NI, LlsfState.NI, LlsfState.NI_END, LlsfState.NULL])
        self.assertEqual([header.size for header in headers], [7, 12, 12, 2, 0, 0])
        self.assertTrue(ChildLlsf.parse(acknowledgement_for_parent_ni(LlsfState.NI, 1, 2) or b"").acknowledge)
