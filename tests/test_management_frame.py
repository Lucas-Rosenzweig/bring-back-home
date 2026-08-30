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
