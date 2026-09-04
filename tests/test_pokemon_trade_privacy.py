from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILENAMES = {"prod.keys", "passphrase", "ldn.passphrase"}
SYNTHETIC_SESSION = {
    "ssid": "00112233445566778899aabbccddeeff",
    "interface": "synthetic0",
    "local": {"ip_address": "169.254.1.2", "mac_address": "02:00:00:00:00:02"},
    "host": {"ip_address": "169.254.1.1", "mac_address": "02:00:00:00:00:01"},
}


class PrivacyGuardTest(unittest.TestCase):
    def test_sensitive_capture_paths_are_ignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("captures/", ignored)
        self.assertIn("*.pcap", ignored)

    def test_versioned_fixtures_do_not_contain_sensitive_file_names(self) -> None:
        fixtures = ROOT / "tests" / "fixtures"
        if not fixtures.exists():
            return
        for path in fixtures.rglob("*"):
            self.assertNotIn(path.name.lower(), FORBIDDEN_FILENAMES)

    def test_jsonl_fixtures_use_only_allowlisted_synthetic_sessions(self) -> None:
        fixtures = ROOT / "tests" / "fixtures"
        for path in fixtures.rglob("*.jsonl"):
            plaintext = path.read_text(encoding="utf-8")
            header = json.loads(plaintext.splitlines()[0])
            session = header["session"]
            for key, expected in SYNTHETIC_SESSION.items():
                self.assertEqual(session[key], expected, path)
            self.assertNotIn("prod.keys", plaintext.lower())
            self.assertNotIn("passphrase", plaintext.lower())
