import unittest

from IEEE80211.parsing.ByteReader import ByteReader


class ByteReaderTest(unittest.TestCase):
    def test_reads_sequential_values(self) -> None:
        reader = ByteReader(b"\x12\x34\x56\x78")

        self.assertEqual(reader.read_u8("first byte"), 0x12)
        self.assertEqual(reader.read_u16_be("word"), 0x3456)
        self.assertEqual(reader.read_remaining(), b"\x78")
        self.assertEqual(reader.offset, 4)
        self.assertEqual(reader.remaining, 0)

    def test_rejects_truncated_read_with_offset(self) -> None:
        reader = ByteReader(b"\x12")

        with self.assertRaisesRegex(
            ValueError,
            "Truncated two-byte field at offset 0: expected 2 bytes, only 1 available",
        ):
            _ = reader.read_bytes(2, "two-byte field")


if __name__ == "__main__":
    _ = unittest.main()
