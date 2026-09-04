from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.gba.barriers import BarrierKind, BarrierResponder
from pokemon_trade.games.frlg.gba.rfu import RfuSlot


class BarrierResponderTest(unittest.TestCase):
    def test_initiated_standby_requires_a_matching_host_count(self) -> None:
        responder = BarrierResponder()
        responder.begin(BarrierKind.STANDBY)
        self.assertEqual(responder.outgoing(), RfuSlot((0x6600, 0, 0, 0, 0, 0, 0)))
        self.assertFalse(responder.observe(RfuSlot((0x6600, 1, 0, 0, 0, 0, 0))))
        self.assertTrue(responder.observe(RfuSlot((0x6600, 0, 0, 0, 0, 0, 0))))
        self.assertEqual(responder.next_standby_count, 1)
        self.assertEqual(
            responder.outgoing(), RfuSlot((0x6600, 0, 0, 0, 0, 0, 0))
        )
        self.assertIsNone(responder.outgoing())

    def test_repeated_completed_count_does_not_reopen_standby(self) -> None:
        responder = BarrierResponder(max_emits=1)
        responder.begin(BarrierKind.STANDBY)
        self.assertIsNotNone(responder.outgoing())
        completed = RfuSlot((0x6600, 0, 0, 0, 0, 0, 0))

        self.assertTrue(responder.observe(completed))
        self.assertFalse(responder.observe(completed))
        self.assertEqual(responder.outgoing(), completed)
        self.assertFalse(responder.observe(completed))
        self.assertFalse(responder.active)
        self.assertIsNone(responder.outgoing())

    def test_reactive_close_mirrors_the_host_until_teardown(self) -> None:
        responder = BarrierResponder()
        self.assertFalse(responder.observe(RfuSlot((0x5F00, 7, 0, 0, 0, 0, 0))))
        self.assertEqual(responder.outgoing(), RfuSlot((0x5F00, 7, 0, 0, 0, 0, 0)))

    def test_live_emission_cap_lets_reliable_retransmit_the_barrier(self) -> None:
        responder = BarrierResponder(max_emits=2)
        responder.begin(BarrierKind.STANDBY)
        expected = RfuSlot((0x6600, 0, 0, 0, 0, 0, 0))
        self.assertEqual(responder.outgoing(), expected)
        self.assertEqual(responder.outgoing(), expected)
        self.assertIsNone(responder.outgoing())

    def test_rearm_starts_a_new_bounded_burst_without_changing_count(self) -> None:
        responder = BarrierResponder(max_emits=1)
        responder.begin(BarrierKind.STANDBY)
        self.assertEqual(responder.outgoing(), RfuSlot((0x6600, 0, 0, 0, 0, 0, 0)))
        self.assertIsNone(responder.outgoing())
        responder.rearm()
        self.assertEqual(responder.outgoing(), RfuSlot((0x6600, 0, 0, 0, 0, 0, 0)))
