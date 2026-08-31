import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Wifi.LinuxRadioLease import LinuxRadioLease

IW_DEV = """phy#0
\tInterface wlan0
\t\ttype managed
"""


class TestRadioLease(LinuxRadioLease):
    __test__ = False

    def __init__(self, rule_path: Path) -> None:
        super().__init__(
            "phy0",
            {"mon0", "ldnclient"},
            rule_path=rule_path,
            settle_seconds=0,
            require_root=False,
        )
        self.commands: list[tuple[str, ...]] = []
        self.managed_changes: list[tuple[str, bool]] = []

    def _run(
        self,
        command: list[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        self.commands.append(normalized)
        stdout = IW_DEV if normalized == ("iw", "dev") else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def _link_is_up(self, interface: str) -> bool:
        return True

    def _managed_state(self, interface: str) -> bool | None:
        return True

    def _set_managed(self, interface: str, managed: bool) -> None:
        self.managed_changes.append((interface, managed))


class LinuxRadioLeaseTest(unittest.TestCase):
    def test_excludes_transient_interfaces_and_restores_wlan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            rule_path = Path(temporary_directory) / "ldn.conf"
            lease = TestRadioLease(rule_path)

            with (
                patch(
                    "Wifi.LinuxRadioLease.shutil.which",
                    return_value="/usr/bin/nmcli",
                ),
                lease,
            ):
                self.assertTrue(rule_path.exists())
                self.assertIn("interface-name:ldnclient", rule_path.read_text())
                self.assertIn("interface-name:mon0", rule_path.read_text())

            self.assertFalse(rule_path.exists())
            self.assertEqual(
                lease.managed_changes,
                [("wlan0", False), ("wlan0", True)],
            )
            self.assertIn(
                ("ip", "link", "set", "dev", "wlan0", "down"),
                lease.commands,
            )
            self.assertIn(
                ("ip", "link", "set", "dev", "wlan0", "up"),
                lease.commands,
            )


if __name__ == "__main__":
    unittest.main()
