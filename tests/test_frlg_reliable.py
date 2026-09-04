from __future__ import annotations

import unittest

from pokemon_trade.errors import TradeTimeoutError
from pokemon_trade.games.frlg.pia.reliable import ReliableChannel, ReliableFrame, ReliableWireFrame, next_sequence


class ReliableChannelTest(unittest.TestCase):
    def test_loss_duplicate_reordering_and_acknowledgement(self) -> None:
        sender = ReliableChannel()
        receiver = ReliableChannel()
        first = sender.queue(b"one")
        second = sender.queue(b"two")
        frames = sender.poll(0)

        self.assertEqual(receiver.receive(frames[1]), ())
        self.assertEqual(receiver.receive(frames[0]), (b"one", b"two"))
        self.assertEqual(receiver.receive(frames[0]), ())
        sender.receive(receiver.acknowledge_only())

        self.assertEqual(sender.pending_sequences, ())
        self.assertEqual((first, second), (1, 2))

    def test_wraps_without_zero_and_bounds_retransmission(self) -> None:
        self.assertEqual(next_sequence(0xFFFF), 1)
        channel = ReliableChannel(rto_seconds=1, max_attempts=1)
        channel.queue(b"payload")
        channel.poll(0)
        with self.assertRaises(TradeTimeoutError):
            channel.poll(1)

    def test_wire_envelope_is_strict_and_unicast(self) -> None:
        frame = ReliableWireFrame(0x0F, 0xFFF0, 0xFFF0, b"metadata")
        self.assertEqual(ReliableWireFrame.parse(frame.encode()), frame)
