from contextlib import redirect_stdout
from io import StringIO
import unittest

from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame
from IEEE80211.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211.body.action.IEEE80211VendorSpecificAction import IEEE80211VendorSpecificAction
from IEEE80211.body.action.nintendo.NintendoLdnAction import NintendoLdnAction
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisement import NintendoLdnAdvertisement
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisementFormat import (
    NintendoLdnAdvertisementFormat,
)
from IEEE80211.body.action.nintendo.NintendoLdnPacketType import NintendoLdnPacketType


MANAGEMENT_HEADER_REMAINDER = b"\x00" * 22


def nintendo_ldn_advertisement_body(ciphertext: bytes = b"\xde\xad\xbe") -> bytes:
    session_info = bytes(range(32))
    return (
        b"\x7f"
        + b"\x00\x22\xaa"
        + b"\x04\x00"
        + b"\x01\x01"
        + b"\x00" * 4
        + session_info
        + b"\x04"
        + b"\x03"
        + len(ciphertext).to_bytes(2, "big")
        + b"\x10\x20\x30\x40"
        + bytes(range(0xA0, 0xB0))
        + ciphertext
    )


def management_action_frame(body: bytes) -> bytes:
    return b"\xd0\x00" + MANAGEMENT_HEADER_REMAINDER + body


class NintendoLdnActionTest(unittest.TestCase):
    def test_parses_nintendo_ldn_aes_gcm_advertisement(self) -> None:
        frame = IEEE80211ManagementFrame(
            management_action_frame(nintendo_ldn_advertisement_body())
        )

        body = frame.body
        self.assertIsInstance(body, IEEE80211ActionBody)
        assert isinstance(body, IEEE80211ActionBody)
        self.assertEqual(body.category, 0x7F)

        vendor_action = body.action
        self.assertIsInstance(vendor_action, IEEE80211VendorSpecificAction)
        assert isinstance(vendor_action, IEEE80211VendorSpecificAction)
        self.assertEqual(vendor_action.oui, b"\x00\x22\xaa")

        ldn_action = vendor_action.vendor_action
        self.assertIsInstance(ldn_action, NintendoLdnAction)
        assert isinstance(ldn_action, NintendoLdnAction)
        self.assertEqual(ldn_action.packet_type, NintendoLdnPacketType.ADVERTISEMENT)

        advertisement = ldn_action.payload
        self.assertIsInstance(advertisement, NintendoLdnAdvertisement)
        assert isinstance(advertisement, NintendoLdnAdvertisement)
        self.assertEqual(advertisement.session_info.raw, bytes(range(32)))
        self.assertEqual(advertisement.ldn_version, 4)
        self.assertEqual(
            advertisement.encryption_type,
            NintendoLdnAdvertisementFormat.AES_GCM,
        )
        self.assertEqual(advertisement.data_size, 3)
        self.assertEqual(advertisement.nonce, b"\x10\x20\x30\x40")
        self.assertEqual(advertisement.gcm_tag, bytes(range(0xA0, 0xB0)))
        self.assertEqual(advertisement.encrypted_advertisement_data, b"\xde\xad\xbe")
        self.assertTrue(advertisement.is_encrypted)

    def test_prints_nintendo_ldn_advertisement_hierarchy(self) -> None:
        frame = IEEE80211ManagementFrame(
            management_action_frame(nintendo_ldn_advertisement_body())
        )
        output = StringIO()

        with redirect_stdout(output):
            frame.print()

        rendered = output.getvalue()
        self.assertIn("Category           : 0x7F", rendered)
        self.assertIn("Vendor-Specific Action:", rendered)
        self.assertIn("OUI                 : 00:22:aa", rendered)
        self.assertIn("Nintendo LDN Action:", rendered)
        self.assertIn("Packet Type         : ADVERTISEMENT", rendered)
        self.assertIn("Advertisement Payload:", rendered)
        self.assertIn("LDN Version         : 4", rendered)
        self.assertIn("Encryption Type     : AES_GCM", rendered)
        self.assertIn("Data Size           : 3", rendered)
        self.assertIn("Nonce               : 10 20 30 40", rendered)
        self.assertIn(
            "GCM Tag             : a0 a1 a2 a3 a4 a5 a6 a7 a8 a9 aa ab ac ad ae af",
            rendered,
        )
        self.assertIn("Encrypted Data      : de ad be", rendered)

    def test_rejects_truncated_gcm_tag(self) -> None:
        body = nintendo_ldn_advertisement_body()[:-19]

        with self.assertRaisesRegex(ValueError, "Truncated GCM authentication tag"):
            _ = IEEE80211ManagementFrame(management_action_frame(body))


if __name__ == "__main__":
    _ = unittest.main()
