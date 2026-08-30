from contextlib import redirect_stdout
from io import StringIO
import unittest

from IEEE80211Frame.IEEE80211ManagementFrame import IEEE80211ManagementFrame
from IEEE80211Frame.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211Frame.header.IEEE80211ManagementHeader import IEEE80211ManagementHeader


MANAGEMENT_HEADER_REMAINDER = b"\x00" * 22


def management_frame(subtype: int, body: bytes) -> bytes:
    frame_control = bytes((subtype << 4, 0))
    return frame_control + MANAGEMENT_HEADER_REMAINDER + body


class IEEE80211ManagementFrameTest(unittest.TestCase):
    def test_parses_action_frame_header_and_body_separately(self) -> None:
        raw = management_frame(13, b"\x04\x01\x02")

        frame = IEEE80211ManagementFrame(raw)

        self.assertEqual(frame.header.raw, raw[:24])
        body = frame.body
        self.assertIsInstance(body, IEEE80211ActionBody)
        assert isinstance(body, IEEE80211ActionBody)
        self.assertEqual(body.category, 4)
        self.assertEqual(body.action_data, b"\x01\x02")

    def test_prints_management_header_and_action_body(self) -> None:
        raw = (
            b"\xd0\x00"
            + b"\x34\x12"
            + b"\x00\x11\x22\x33\x44\x55"
            + b"\xaa\xbb\xcc\xdd\xee\xff"
            + b"\x10\x20\x30\x40\x50\x60"
            + b"\x78\x56"
            + b"\x04\x01\x02"
        )
        frame = IEEE80211ManagementFrame(raw)
        output = StringIO()

        with redirect_stdout(output):
            frame.print()

        rendered = output.getvalue()
        self.assertIn("IEEE 802.11 Management Frame:", rendered)
        self.assertIn("  Management Header:", rendered)
        self.assertIn("    Frame Control:", rendered)
        self.assertIn("    Duration           : 34 12", rendered)
        self.assertIn("    Address 1          : 00:11:22:33:44:55", rendered)
        self.assertIn("    Address 2          : aa:bb:cc:dd:ee:ff", rendered)
        self.assertIn("    Address 3          : 10:20:30:40:50:60", rendered)
        self.assertIn("    Sequence Control   : 78 56", rendered)
        self.assertIn("  Action Body:", rendered)
        self.assertIn("    Category           : 4", rendered)
        self.assertIn("    Action Data        : 01 02", rendered)

    def test_rejects_non_management_frame(self) -> None:
        data_frame = b"\x08\x00" + MANAGEMENT_HEADER_REMAINDER

        with self.assertRaisesRegex(ValueError, "not a management frame"):
            _ = IEEE80211ManagementFrame(data_frame)

    def test_rejects_unsupported_management_subtype(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "Unsupported management subtype 8"):
            _ = IEEE80211ManagementFrame(management_frame(8, b""))

    def test_rejects_action_frame_without_category(self) -> None:
        with self.assertRaisesRegex(ValueError, "Action body must contain a category"):
            _ = IEEE80211ManagementFrame(management_frame(13, b""))

    def test_rejects_management_header_with_wrong_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "Management header should be 24 bytes long"):
            _ = IEEE80211ManagementHeader(b"\x00" * 25)


if __name__ == "__main__":
    _ = unittest.main()
