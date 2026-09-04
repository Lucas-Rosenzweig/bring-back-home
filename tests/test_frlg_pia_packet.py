from __future__ import annotations

import unittest

from pokemon_trade.errors import CryptoError, MalformedDatagramError
from pokemon_trade.games.frlg.pia.crypto import (
    decrypt_frlg_v16,
    decrypt_gcm,
    encrypt_frlg_v16,
    encrypt_gcm,
    ldn_nonce,
)
from pokemon_trade.games.frlg.pia.packet import (
    PiaMessage,
    PiaPacketV11,
    PiaPacketV16,
    compress_packet_payload,
    decode_messages,
    decompress_packet_payload,
    encode_messages,
    encode_messages_v16,
    decode_messages_v16,
)


class PiaPacketTest(unittest.TestCase):
    def test_packet_and_message_round_trip(self) -> None:
        messages = (
            PiaMessage(0, 9, 0x123456, 7, b"first"),
            PiaMessage(1, 9, 0x123456, 7, b"second"),
        )
        packet = PiaPacketV11(True, 2, 1, 8, bytes(8), bytes(8), encode_messages(messages), b"\x00\x07")

        decoded = PiaPacketV11.parse(packet.encode())

        self.assertEqual(decoded, packet)
        self.assertEqual(decode_messages(decoded.payload), messages)

    def test_rejects_invalid_message_and_header_data(self) -> None:
        with self.assertRaises(MalformedDatagramError):
            PiaPacketV11.parse(b"bad")
        encoded = bytearray(encode_messages((PiaMessage(0, 1, 2, 3, b"x"),)))
        encoded[-1] = 1
        with self.assertRaises(MalformedDatagramError):
            decode_messages(bytes(encoded))
        with self.assertRaises(MalformedDatagramError):
            decode_messages(b"\x03\x00")

    def test_zstd_and_gcm_reject_corruption(self) -> None:
        self.assertEqual(decompress_packet_payload(compress_packet_payload(b"payload")), b"payload")
        nonce = ldn_nonce(0x11223344, "169.254.1.2", bytes(range(8)))
        ciphertext, tag = encrypt_gcm(bytes(range(16)), nonce, b"payload", b"header")
        self.assertEqual(decrypt_gcm(bytes(range(16)), nonce, ciphertext, tag, b"header"), b"payload")
        with self.assertRaises(CryptoError):
            decrypt_gcm(bytes(range(16)), nonce, ciphertext, tag[:-1] + b"x", b"header")

    def test_v16_header_and_message_tiling(self) -> None:
        messages = (PiaMessage(0, 10, 0, 0, b"reliable"),)
        packet = PiaPacketV16(True, 0x02, 2, 1, 7, bytes(8), bytes(8), encode_messages_v16(messages), 0)
        self.assertEqual(PiaPacketV16.parse(packet.encode()), packet)
        self.assertEqual(decode_messages_v16(packet.payload), messages)

    def test_v16_first_message_may_omit_zero_message_flags(self) -> None:
        # PIA v6 hosts serialize a first message as `0x06 size protocol ...`
        # when its message flags are zero.
        encoded = b"\x06\x00\x03\x01net"
        self.assertEqual(
            decode_messages_v16(encoded),
            (PiaMessage(0, 1, 0, 0, b"net"),),
        )

    def test_v16_rejects_a_truncated_protocol_extension(self) -> None:
        with self.assertRaises(MalformedDatagramError):
            decode_messages_v16(b"\x16\x00\x01\x0A")

    def test_v16_crypto_round_trip_keeps_footer_outside_application(self) -> None:
        packet = encrypt_frlg_v16(
            ssid=bytes(range(16)), game_key=bytes(range(16)), source_ip="169.254.1.2",
            destination_variable_id=2, source_variable_id=1, packet_id=3, nonce=bytes(range(8)),
            application=b"application", footer=b"\x00\x02", establishing=True,
        )
        self.assertEqual(decrypt_frlg_v16(packet, bytes(range(16)), bytes(range(16)), "169.254.1.2"), (b"application", b"\x00\x02"))
