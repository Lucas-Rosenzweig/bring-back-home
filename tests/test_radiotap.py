import unittest

from IEEE80211.radiotap import extract_frame


class RadiotapTest(unittest.TestCase):
    def test_extracts_channel_and_removes_fcs(self) -> None:
        frame = b"\xD0\x00payload"
        packet = (
            b"\x00\x00"
            + (14).to_bytes(2, "little")
            + ((1 << 1) | (1 << 3)).to_bytes(4, "little")
            + b"\x10"  # flags: frame includes FCS
            + b"\x00"  # channel alignment
            + (2412).to_bytes(2, "little")
            + b"\x00\x00"
            + frame
            + b"FCS!"
        )

        self.assertEqual(extract_frame(packet), (frame, 1))

    def test_walks_extended_presence_words(self) -> None:
        frame = b"frame"
        packet = (
            b"\x00\x00"
            + (16).to_bytes(2, "little")
            + ((1 << 3) | (1 << 31)).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (5180).to_bytes(2, "little")
            + b"\x00\x00"
            + frame
        )

        self.assertEqual(extract_frame(packet), (frame, 36))

    def test_rejects_invalid_header(self) -> None:
        self.assertIsNone(extract_frame(b"not radiotap"))


if __name__ == "__main__":
    unittest.main()
