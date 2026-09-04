from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_trade.transport.ldn_discovery import read_passphrases


class LdnDiscoveryTest(unittest.TestCase):
    def test_reads_passphrase_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "passphrase"
            path.write_bytes(b"secret\n")

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(read_passphrases(path, "LDN_TEST_PASSWORD").fallback, b"secret")

    def test_environment_passphrase_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"LDN_TEST_PASSWORD": "from-env"}):
            loaded = read_passphrases(None, "LDN_TEST_PASSWORD")

        self.assertEqual(loaded.fallback, b"from-env")

    def test_reads_hex_passphrases_from_toml_by_communication_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "passphrases.toml"
            path.write_text('[passphrases]\n"01006FA0233F8000" = "aa55"\n')

            with patch.dict(os.environ, {}, clear=True):
                passphrases = read_passphrases(path, "LDN_TEST_PASSWORD")

            self.assertEqual(passphrases.get(0x01006FA0233F8000), b"\xaa\x55")
            self.assertIsNone(passphrases.get(0x0100A3D008C5C000))


if __name__ == "__main__":
    unittest.main()
