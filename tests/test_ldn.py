import unittest
from io import StringIO

from IEEE80211.ldn import AES_GCM, LdnAdvertisement, parse_ldn_advertisement


def advertisement_frame(data: bytes = b"\xde\xad\xbe") -> bytes:
    payload = (
        bytes(range(32))
        + b"\x04"
        + bytes((AES_GCM,))
        + len(data).to_bytes(2, "big")
        + b"\x10\x20\x30\x40"
        + bytes(range(0xA0, 0xB0))
        + data
    )
    action = (
        b"\x7f" + b"\x00\x22\xaa" + b"\x04\x00" + b"\x01\x01" + b"\x00" * 4 + payload
    )
    return b"\xd0\x00" + b"\x00" * 22 + action


class LdnParserTest(unittest.TestCase):
    def test_parses_aes_gcm_advertisement(self) -> None:
        advertisement = parse_ldn_advertisement(advertisement_frame())

        self.assertIsInstance(advertisement, LdnAdvertisement)
        assert advertisement is not None
        self.assertEqual(advertisement.session_info, bytes(range(32)))
        self.assertEqual(advertisement.ldn_version, 4)
        self.assertEqual(advertisement.encryption_type, AES_GCM)
        self.assertEqual(advertisement.data_size, 3)
        self.assertEqual(advertisement.nonce, b"\x10\x20\x30\x40")
        self.assertEqual(advertisement.authentication_tag, bytes(range(0xA0, 0xB0)))
        self.assertEqual(advertisement.advertisement_data, b"\xde\xad\xbe")
        self.assertTrue(advertisement.is_encrypted)

    def test_decodes_clear_network_id_fields(self) -> None:
        raw = advertisement_frame()
        network_id = (
            (0x0100A3D008C5C000).to_bytes(8, "big")
            + b"\x00\x00"
            + (4).to_bytes(2, "big")
            + b"\x00" * 4
            + bytes(range(16))
        )
        payload_offset = 24 + 12
        raw = raw[:payload_offset] + network_id + raw[payload_offset + 32 :]

        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None

        self.assertEqual(advertisement.local_communication_id, 0x0100A3D008C5C000)
        self.assertEqual(advertisement.scene_id, 4)
        self.assertEqual(advertisement.ssid, bytes(range(16)))

    def test_ignores_unrelated_frames(self) -> None:
        self.assertIsNone(parse_ldn_advertisement(b"\x08\x00" + b"\x00" * 40))
        self.assertIsNone(
            parse_ldn_advertisement(
                advertisement_frame().replace(b"\x00\x22\xaa", b"BAD")
            )
        )

    def test_rejects_truncated_target_advertisement(self) -> None:
        with self.assertRaisesRegex(ValueError, "truncated data"):
            parse_ldn_advertisement(advertisement_frame()[:-1])

    def test_displays_the_decoded_frame(self) -> None:
        advertisement = parse_ldn_advertisement(advertisement_frame(b"Hi!"))
        assert advertisement is not None
        output = StringIO()

        advertisement.display(file=output)

        rendered = output.getvalue()
        self.assertIn("Nintendo LDN advertisement:", rendered)
        self.assertIn("Frame control      : d0 00", rendered)
        self.assertIn("Encryption         : AES_GCM (0x03)", rendered)
        self.assertIn("Advertisement data : 48 69 21", rendered)
        self.assertIn("ASCII preview      : Hi!", rendered)
        self.assertIn(
            f"Raw frame          : {advertisement.raw_frame.hex(' ')}", rendered
        )


if __name__ == "__main__":
    unittest.main()
