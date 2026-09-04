from __future__ import annotations

import unittest

from pokemon_trade.errors import MalformedDatagramError
from pokemon_trade.games.frlg.gba.frame import (
    AcknowledgeFrame,
    ChildSlotFrame,
    HostSlotFrame,
    HostTimestampAcker,
    parse_frame,
)


class GbaFrameTest(unittest.TestCase):
    def test_child_and_host_slot_layouts_are_distinct(self) -> None:
        child = ChildSlotFrame(4, b"abc")
        self.assertEqual(child.encode(), b"WT\x0c\0\x04\0\0\0\0\x03\0\0abc\0")
        host_wire = b"WT\x0c\0\x04\0\0\0\x03\0\0\0abc\0"
        self.assertEqual(parse_frame(host_wire), HostSlotFrame(4, b"abc"))

    def test_acknowledges_each_unique_host_timestamp_once(self) -> None:
        acker = HostTimestampAcker()
        frame = HostSlotFrame(9, b"")
        self.assertEqual(acker.acknowledge(frame, 2), AcknowledgeFrame(1, 2, 9))
        self.assertIsNone(acker.acknowledge(frame, 3))

    def test_rejects_inconsistent_lengths(self) -> None:
        with self.assertRaises(MalformedDatagramError):
            parse_frame(b"WT\x08\0\x01\0\0\0\x04")

    def test_accepts_a_host_slot_with_adapter_suffix(self) -> None:
        host_wire = b"WT\x0c\0\x04\0\0\0\x03\0\0\0abc\x99"
        self.assertEqual(parse_frame(host_wire), HostSlotFrame(4, b"abc"))

    def test_accepts_the_compact_host_idle_heartbeat(self) -> None:
        self.assertEqual(parse_frame(b"WT\x05\0\x09\0\0\0\x01"), HostSlotFrame(9, b""))
