from __future__ import annotations

import unittest

from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16, encrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import PiaMessage as PacketMessage
from pokemon_trade.games.frlg.pia.packet import PiaPacketV16, decode_messages_v16, encode_messages_v16
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.session import PiaProtocol, PiaSession


class PiaPeerTest(unittest.TestCase):
    def test_default_packet_nonces_are_a_single_monotonic_counter(self) -> None:
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        peer = PiaPeer(
            session,
            ssid=bytes(range(16)),
            game_key=bytes(range(16)),
            local_ip="169.254.1.2",
        )

        first = PiaPacketV16.parse(peer.encode_data_batch(PiaProtocol.RELIABLE, (b"a",)))
        second = PiaPacketV16.parse(peer.encode_data_batch(PiaProtocol.RELIABLE, (b"b",)))

        self.assertEqual(
            int.from_bytes(second.nonce, "big"),
            (int.from_bytes(first.nonce, "big") + 1) & 0xFFFFFFFFFFFFFFFF,
        )

    def test_compresses_a_batch_at_the_frlg_size_threshold(self) -> None:
        ssid = bytes(range(16))
        key = bytes(range(16))
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        peer = PiaPeer(session, ssid=ssid, game_key=key, local_ip="169.254.1.2", nonce_source=lambda _: bytes(8))

        packet = PiaPacketV16.parse(peer.encode_data_batch(PiaProtocol.RELIABLE, (bytes(30), bytes(30))))
        self.assertTrue(packet.flags & 1)
        body, _ = decrypt_frlg_v16(packet, ssid, key, "169.254.1.2")
        self.assertEqual(len(decode_messages_v16(body)), 2)

    def test_preserves_per_message_flags_in_a_reliable_batch(self) -> None:
        ssid = bytes(range(16))
        key = bytes(range(16))
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        peer = PiaPeer(session, ssid=ssid, game_key=key, local_ip="169.254.1.2")

        encoded = peer.encode_data_batch(
            PiaProtocol.RELIABLE,
            (b"data", b"ack"),
            message_flags=(0, 0x40),
        )
        body, _ = decrypt_frlg_v16(PiaPacketV16.parse(encoded), ssid, key, "169.254.1.2")

        self.assertEqual([message.flags for message in decode_messages_v16(body)], [0, 0x40])

    def test_accepts_a_session_control_footer_distinct_from_header_destination(self) -> None:
        ssid = bytes(range(16))
        key = bytes(range(16))
        session = PiaSession(
            local_constant_id=bytes.fromhex("010203040506"),
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        peer = PiaPeer(session, ssid=ssid, game_key=key, local_ip="169.254.1.2")
        peer.begin(bytes.fromhex("A1A2A3A4A5A6"), 0x1111)
        peer.drain()
        incoming = encrypt_frlg_v16(
            ssid=ssid,
            game_key=key,
            source_ip="169.254.1.1",
            destination_variable_id=1,
            source_variable_id=0x2222,
            packet_id=1,
            nonce=b"12345678",
            application=encode_messages_v16((PacketMessage(0, PiaProtocol.NET, 0, 0, b"\x01\x50\0\0" + (7).to_bytes(4, "big")),)),
            footer=b"\x11\x11",
        ).encode()

        self.assertEqual(peer.receive(incoming, "169.254.1.1"), ())
        self.assertEqual(session.local_variable_id, 0x1111)
        self.assertEqual(session.host_variable_id, 0x2222)

    def test_queues_an_encrypted_initial_session_join(self) -> None:
        ssid = bytes(range(16))
        key = bytes(range(16))
        peer = PiaPeer(
            PiaSession(local_constant_id=bytes.fromhex("010203040506"), local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88),
            ssid=ssid,
            game_key=key,
            local_ip="169.254.1.2",
            nonce_source=lambda _: bytes(8),
        )

        peer.begin(bytes.fromhex("A1A2A3A4A5A6"), 0x1111)

        packet = PiaPacketV16.parse(peer.drain()[0])
        body, footer = decrypt_frlg_v16(packet, ssid, key, "169.254.1.2")
        self.assertEqual(packet.destination_variable_id, 0)
        self.assertEqual(packet.source_variable_id, 0x1111)
        self.assertEqual(packet.packet_id, 0)
        self.assertEqual(footer, b"")
        self.assertEqual(decode_messages_v16(body)[0].protocol_type, PiaProtocol.SESSION)

    def test_replies_to_encrypted_net_request_with_real_pia_datagrams(self) -> None:
        ssid = bytes(range(16))
        key = bytes(range(16))
        peer = PiaPeer(
            PiaSession(local_constant_id=bytes.fromhex("010203040506"), local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88),
            ssid=ssid, game_key=key, local_ip="169.254.1.2", nonce_source=lambda _: bytes(8),
        )
        request = b"\x01\x11\0\x0c" + (4).to_bytes(4, "big") + (0x2222).to_bytes(2, "big") + bytes.fromhex("E5395B69D280")
        incoming = encrypt_frlg_v16(
            ssid=ssid, game_key=key, source_ip="169.254.1.1", destination_variable_id=0x1111, source_variable_id=0x2222,
            packet_id=1, nonce=b"12345678", application=encode_messages_v16((PacketMessage(0, PiaProtocol.NET, 0, 0, request),)), footer=b"\x11\x11",
        ).encode()

        self.assertEqual(peer.receive(incoming, "169.254.1.1"), ())
        responses = peer.drain()
        self.assertEqual(len(responses), 2)
        first = PiaPacketV16.parse(responses[0])
        body, _ = decrypt_frlg_v16(first, ssid, key, "169.254.1.2")
        self.assertEqual(decode_messages_v16(body)[0].protocol_type, PiaProtocol.NET)
        self.assertEqual(first.packet_id, 0)
