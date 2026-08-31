import subprocess
import unittest
from collections.abc import Sequence
from typing import Any
from unittest.mock import patch

from Wifi.LinuxMonitor import LinuxMonitor

IW_DEV = """phy#0
\tInterface wlan0
\t\ttype managed
"""

IW_DEV_WITH_MONITOR = """phy#0
\tInterface mon0
\t\ttype monitor
\tInterface wlan0
\t\ttype managed
"""


class FakeSocket:
    def __init__(self, bind_error: BaseException | None = None) -> None:
        self.bind_error = bind_error
        self.closed = False
        self.bound_to: tuple[str, int] | None = None
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def bind(self, address: tuple[str, int]) -> None:
        if self.bind_error is not None:
            raise self.bind_error
        self.bound_to = address

    def close(self) -> None:
        self.closed = True

    def recvfrom(self, size: int) -> tuple[bytes, object]:
        raise TimeoutError


class TestMonitor(LinuxMonitor):
    __test__ = False

    def __init__(self, iw_dev: str = IW_DEV, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.iw_dev = iw_dev
        self.commands: list[tuple[str, ...]] = []
        self.managed_changes: list[tuple[str, bool]] = []

    def _run(
        self,
        command: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        self.commands.append(normalized)
        stdout = ""
        if normalized == ("iw", "dev"):
            stdout = self.iw_dev
        elif normalized == ("iw", "dev", self.mon_iface, "info"):
            stdout = "channel 1 (2412 MHz)\n"
        elif normalized == ("iw", "phy", self.phy, "info"):
            stdout = "* 2412.0 MHz [1]\n* 2437.0 MHz [6]\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def _link_is_up(self, interface: str) -> bool:
        return True

    def _network_manager_state(self, interface: str) -> bool | None:
        return True

    def _set_managed(self, interface: str, managed: bool) -> None:
        self.managed_changes.append((interface, managed))


class LinuxMonitorLifecycleTest(unittest.TestCase):
    def test_reads_current_network_manager_managed_field(self) -> None:
        result = subprocess.CompletedProcess(
            ["nmcli"],
            0,
            stdout="yes\n",
            stderr="",
        )
        monitor = LinuxMonitor()

        with (
            patch("Wifi.LinuxMonitor.shutil.which", return_value="/usr/bin/nmcli"),
            patch("Wifi.LinuxMonitor.subprocess.run", return_value=result) as run,
        ):
            self.assertTrue(monitor._network_manager_state("wlan0"))

        self.assertEqual(
            run.call_args.args[0],
            [
                "nmcli",
                "-g",
                "GENERAL.NM-MANAGED",
                "device",
                "show",
                "wlan0",
            ],
        )

    def test_context_owns_monitor_and_restores_other_interface(self) -> None:
        fake_socket = FakeSocket()
        monitor = TestMonitor(initial_channel=1)

        with (
            patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket),
            monitor,
        ):
            self.assertEqual(fake_socket.bound_to, ("mon0", 0))
            self.assertIn(
                ("ip", "link", "set", "dev", "wlan0", "down"),
                monitor.commands,
            )

        self.assertTrue(fake_socket.closed)
        self.assertIn(("iw", "dev", "mon0", "del"), monitor.commands)
        self.assertIn(
            ("ip", "link", "set", "dev", "wlan0", "up"),
            monitor.commands,
        )
        self.assertEqual(
            monitor.managed_changes,
            [("wlan0", False), ("wlan0", True)],
        )

    def test_existing_monitor_requires_explicit_replacement(self) -> None:
        monitor = TestMonitor(iw_dev=IW_DEV_WITH_MONITOR)

        with self.assertRaisesRegex(RuntimeError, "replace_existing=True"):
            monitor.open()

        self.assertEqual(
            monitor.commands,
            [("iw", "dev")],
        )

    def test_explicitly_replaces_and_then_deletes_stale_monitor(self) -> None:
        fake_socket = FakeSocket()
        monitor = TestMonitor(
            iw_dev=IW_DEV_WITH_MONITOR,
            replace_existing=True,
        )

        with patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket):
            monitor.open()
            monitor.close()

        deletions = [
            command
            for command in monitor.commands
            if command == ("iw", "dev", "mon0", "del")
        ]
        self.assertEqual(len(deletions), 2)

    def test_open_failure_rolls_back_interface_and_wifi_state(self) -> None:
        fake_socket = FakeSocket(OSError("bind failed"))
        monitor = TestMonitor()

        with (
            patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket),
            self.assertRaisesRegex(OSError, "bind failed"),
        ):
            monitor.open()

        self.assertTrue(fake_socket.closed)
        self.assertIn(("iw", "dev", "mon0", "del"), monitor.commands)
        self.assertEqual(
            monitor.managed_changes,
            [("wlan0", False), ("wlan0", True)],
        )

    def test_hopping_failure_is_raised_by_scan(self) -> None:
        fake_socket = FakeSocket()
        monitor = TestMonitor()

        with patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket):
            monitor.open()
            with patch.object(
                monitor,
                "set_channel",
                side_effect=subprocess.CalledProcessError(1, ["iw"]),
            ):
                monitor.start_channel_hopping((1, 6), dwell_seconds=0.001)
                self.assertTrue(monitor._hopping_stop.wait(1))
                with self.assertRaisesRegex(RuntimeError, "channel hopping failed"):
                    monitor.scan()
            monitor.close()

    def test_channel_change_keeps_monitor_link_up(self) -> None:
        fake_socket = FakeSocket()
        monitor = TestMonitor()

        with patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket):
            monitor.open()
            monitor.set_channel(6)
            monitor.close()

        self.assertIn(
            ("iw", "dev", "mon0", "set", "channel", "6"),
            monitor.commands,
        )
        self.assertNotIn(
            ("ip", "link", "set", "dev", "mon0", "down"),
            monitor.commands,
        )

    def test_rejects_unsupported_channel_before_starting_thread(self) -> None:
        fake_socket = FakeSocket()
        monitor = TestMonitor()

        with patch("Wifi.LinuxMonitor.socket.socket", return_value=fake_socket):
            monitor.open()
            with self.assertRaisesRegex(ValueError, "unsupported.*36"):
                monitor.start_channel_hopping((1, 36))
            self.assertIsNone(monitor._hopping_thread)
            monitor.close()


if __name__ == "__main__":
    unittest.main()
