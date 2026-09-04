from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.gba.blocks import BlockReceiver, BlockSender
from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState, RfuSlot, RfuSlotBuilder, uni_slot


class RfuTest(unittest.TestCase):
    def test_child_uni_slot_and_rolling_tag(self) -> None:
        builder = RfuSlotBuilder()
        first = builder.build(RfuSlot.block_fragment(3, b"x"))
        second = builder.build(RfuSlot.block_fragment(4, b"y"))
        self.assertEqual(first.fragment_index, 3)
        self.assertEqual(second.words[0] >> 5 & 7, 1)
        self.assertEqual(ChildLlsf.parse(uni_slot(first)).state, LlsfState.UNI)

    def test_block_receiver_reassembles_out_of_order_and_deduplicates(self) -> None:
        receiver = BlockReceiver()
        receiver.receive(0, RfuSlot.block_init(2))
        self.assertIsNone(receiver.receive(0, RfuSlot.block_fragment(1, b"second")))
        self.assertIsNone(receiver.receive(0, RfuSlot.block_fragment(1, b"ignored duplicate")))
        result = receiver.receive(0, RfuSlot.block_fragment(0, b"first"))
        self.assertEqual(result, b"first\0\0\0\0\0\0\0" + b"second\0\0\0\0\0\0")

    def test_block_sender_arms_with_four_inits_then_streams_each_fragment_once(self) -> None:
        sender = BlockSender(b"abcdefghijklmn", owner=1)
        slots = []
        while (slot := sender.next_slot()) is not None:
            slots.append(slot)

        self.assertEqual(slots[:4], [RfuSlot.block_init(2, 1)] * 4)
        self.assertEqual(slots[4].fragment_index, 0)
        self.assertEqual(slots[5].fragment_index, 1)
        self.assertTrue(sender.done)

    def test_request_type_is_read_from_word_one(self) -> None:
        request = RfuSlot((0xA100, 3, 0, 0, 0, 0, 0))
        self.assertEqual(request.request_type, 3)
