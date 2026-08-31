import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radio_lab import PROJECT_ROOT, _arguments, _read_passphrases


class RadioLabCliTest(unittest.TestCase):
    def test_defaults_to_project_local_keys_under_sudo(self) -> None:
        args = _arguments(["--discovery-only"])

        self.assertEqual(args.keys, PROJECT_ROOT / ".switch" / "prod.keys")

    def test_reads_passphrase_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "passphrase"
            path.write_bytes(b"secret\n")
            args = _arguments(["--passphrase-file", str(path)])

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(_read_passphrases(args).fallback, b"secret")

    def test_environment_passphrase_takes_precedence(self) -> None:
        args = _arguments(["--passphrase-env", "TEST_LDN_PASSWORD"])

        with patch.dict(os.environ, {"TEST_LDN_PASSWORD": "from-env"}):
            self.assertEqual(_read_passphrases(args).fallback, b"from-env")

    def test_reads_hex_passphrases_from_toml_by_communication_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "passphrases.toml"
            path.write_text('[passphrases]\n"01006FA0233F8000" = "aa55"\n')
            args = _arguments(["--passphrase-file", str(path)])

            with patch.dict(os.environ, {}, clear=True):
                passphrases = _read_passphrases(args)

            self.assertEqual(passphrases.get(0x01006FA0233F8000), b"\xaa\x55")
            self.assertIsNone(passphrases.get(0x0100A3D008C5C000))


if __name__ == "__main__":
    unittest.main()
