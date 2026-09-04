from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.pia.session import (
    PiaMessage,
    PiaProtocol,
    PiaSession,
    PiaSessionPhase,
    parse_net,
)


class PiaSessionTest(unittest.TestCase):
    def test_net_parser_keeps_a_control_trailer_outside_declared_size(self) -> None:
        payload = b"\x01\x50\x00\x00" + (9).to_bytes(4, "big")
        self.assertEqual(parse_net(payload), (1, 0x50, (9).to_bytes(4, "big")))

    def test_negotiates_net_join_finalize_and_rtt_without_fixed_ids(self) -> None:
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes.fromhex("10203040"),
            app_version=88,
        )
        request = b"\x01\x11\0\x0c" + (9).to_bytes(4, "big") + (0x2222).to_bytes(2, "big") + bytes.fromhex("E5395B69D280")

        outbounds = session.ingest(0x1111, 0x2222, PiaMessage(PiaProtocol.NET, request))

        self.assertEqual(session.local_variable_id, 0x1111)
        self.assertEqual(session.host_constant_id, bytes.fromhex("E5395B69D280"))
        self.assertEqual([outbound.message.protocol for outbound in outbounds], [PiaProtocol.NET, PiaProtocol.SESSION])
        self.assertEqual(outbounds[0].message.payload[-4:], (9).to_bytes(4, "big"))
        self.assertTrue(outbounds[1].compressed)
        finalize = session.ingest(0x1111, 0x2222, PiaMessage(PiaProtocol.SESSION, b"\x05\x01"))
        self.assertEqual(finalize[0].message.payload[0], 6)
        self.assertEqual(session.phase, PiaSessionPhase.WAITING_FOR_LIVE_TRAFFIC)
        rtt = session.ingest(0x1111, 0x2222, PiaMessage(PiaProtocol.RTT, bytes(21)))
        self.assertTrue(session.connected)
        self.assertEqual(rtt[0].message.payload[0], 1)

    def test_begins_a_v6_session_join_with_an_unknown_host_variable_id(self) -> None:
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes.fromhex("10203040"),
            app_version=88,
        )

        outbound = session.begin(bytes.fromhex("A1A2A3A4A5A6"), 0x1111)

        self.assertEqual(outbound.message.protocol, PiaProtocol.SESSION)
        self.assertEqual(outbound.destination_variable_id, 0)
        self.assertEqual(outbound.source_variable_id, 0x1111)
        self.assertTrue(outbound.compressed)
        self.assertTrue(outbound.establishing)
        self.assertEqual(outbound.message.payload[0], 0)
        self.assertIn(bytes.fromhex("A1A2A3A4A5A60000"), outbound.message.payload)
