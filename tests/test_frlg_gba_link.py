from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.gba.frame import AcknowledgeFrame, ControlFrame, FrameType, HostSlotFrame, parse_frame
from pokemon_trade.games.frlg.gba.link import CHILD_TIMESTAMP_SEED, RfuFollowerLink
from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState, RfuSlot


class RfuFollowerLinkTest(unittest.TestCase):
    def test_group_control_is_preserved_without_unverified_response(self) -> None:
        frame = ControlFrame(FrameType.GROUP, b"\0\0\0\0")
        self.assertEqual(parse_frame(frame.encode()), frame)
        link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
        self.assertEqual(link.receive(frame, 0).slots, ())
        self.assertEqual(link.drain(), ())

    def test_accept_starts_ni_and_host_uni_slots_are_exposed(self) -> None:
        link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
        self.assertEqual(parse_frame(link.start()), ControlFrame(FrameType.CONNECT, b"\x12\x34"))
        accepted = link.receive(ControlFrame(FrameType.ACCEPT, b"\0\0\x12\x34"), 0)
        self.assertTrue(accepted.accepted)
        link.tick()
        first = link.drain()[0]
        self.assertEqual(first[:2], b"WT")
        self.assertEqual(int.from_bytes(first[4:8], "little"), CHILD_TIMESTAMP_SEED)
        parent_llsf = (int(LlsfState.UNI) << 14).to_bytes(3, "little")
        host = HostSlotFrame(5, parent_llsf + RfuSlot.idle().encode())
        inbound = link.receive(host, 1)
        self.assertTrue(inbound.host_poll_received)
        self.assertEqual(inbound.slots, (RfuSlot.idle(),))
        self.assertEqual(inbound.positional_slots, ((0, RfuSlot.idle()),))
        self.assertIsInstance(parse_frame(link.drain()[0]), AcknowledgeFrame)

    def test_ni_advances_one_tile_per_vblank_without_waiting_for_parent_ack(self) -> None:
        link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
        link.receive(ControlFrame(FrameType.ACCEPT, b"\0\0\x12\x34"), 0)
        link.tick()
        first = link.drain()[0]
        first_header = ChildLlsf.parse(first[12:])
        self.assertEqual(first_header.state, LlsfState.NI_START)

        # PIA Reliable preserves delivery below NI.  The real child sends one
        # new game-data tile each VBlank instead of stop-and-waiting for the
        # parent's acknowledgement of the preceding tile.
        link.tick()
        self.assertEqual(ChildLlsf.parse(link.drain()[0][12:]).state, LlsfState.NI)

    def test_ni_end_and_null_are_consecutive_vblank_tiles(self) -> None:
        link = RfuFollowerLink(b"\x12\x34", b"")
        link.receive(ControlFrame(FrameType.ACCEPT, b"\0\0\x12\x34"), 0)
        link.tick()
        link.drain()  # child NI_START
        link.tick()
        self.assertEqual(ChildLlsf.parse(link.drain()[0][12:]).state, LlsfState.NI_END)
        link.tick()
        self.assertEqual(ChildLlsf.parse(link.drain()[0][12:]).state, LlsfState.NULL)

    def test_acknowledges_each_distinct_host_ni_tile_and_waits_for_host_uni(self) -> None:
        link = RfuFollowerLink(b"\x12\x34", b"")
        link.receive(ControlFrame(FrameType.ACCEPT, b"\0\0\x12\x34"), 0)
        for _ in range(3):
            link.tick()
            link.drain()
        self.assertFalse(link.ready_for_uni)

        parent_ni = (int(LlsfState.NI) << 14 | (1 << 11) | (2 << 9)).to_bytes(3, "little")
        link.receive(HostSlotFrame(1, parent_ni), 1)
        emitted = link.drain()
        self.assertEqual(len(emitted), 2)  # timestamp K plus mirrored host-NI acknowledgement
        ack = ChildLlsf.parse(emitted[1][12:])
        self.assertEqual((ack.state, ack.n, ack.phase, ack.acknowledge), (LlsfState.NI, 1, 2, True))
        duplicate = link.receive(HostSlotFrame(1, parent_ni), 2)
        self.assertTrue(duplicate.host_poll_received)
        self.assertEqual(len(link.drain()), 0)  # same timestamp and NI tile are both deduplicated

        parent_uni = (int(LlsfState.UNI) << 14).to_bytes(3, "little")
        inbound = link.receive(HostSlotFrame(2, parent_uni + RfuSlot.idle().encode()), 3)
        self.assertTrue(inbound.host_uni_entered)
        self.assertTrue(link.ready_for_uni)
