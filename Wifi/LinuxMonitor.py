"""Lifecycle-safe Linux Wi-Fi monitor interface."""

import errno
import os
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import TracebackType

from IEEE80211.radiotap import extract_frame


@dataclass(frozen=True, slots=True)
class _InterfaceState:
    name: str
    was_up: bool
    was_managed: bool | None


class LinuxMonitor:
    """Own a temporary monitor interface and restore the phy on close."""

    def __init__(
        self,
        mon_iface: str = "mon0",
        phy: str = "phy0",
        initial_channel: int | None = None,
        *,
        replace_existing: bool = False,
        socket_timeout: float = 0.25,
        command_timeout: float = 5.0,
    ) -> None:
        self.mon_iface = mon_iface
        self.phy = phy
        self.initial_channel = initial_channel
        self.replace_existing = replace_existing
        self.socket_timeout = socket_timeout
        self.command_timeout = command_timeout

        self.current_channel: int | None = None
        self._configured_channel: int | None = None
        self._socket: socket.socket | None = None
        self._is_open = False
        self._owns_interface = False
        self._saved_interfaces: list[_InterfaceState] = []
        self._channel_lock = threading.Lock()
        self._hopping_stop = threading.Event()
        self._hopping_thread: threading.Thread | None = None
        self._hopping_error: BaseException | None = None

    def _run(
        self,
        command: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=self.command_timeout,
        )

    @staticmethod
    def _interfaces(iw_output: str) -> dict[str, tuple[str, str | None]]:
        interfaces: dict[str, tuple[str, str | None]] = {}
        current_phy: str | None = None
        current_interface: str | None = None

        for line in iw_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("phy#"):
                current_phy = f"phy{stripped.removeprefix('phy#')}"
                current_interface = None
            elif current_phy is not None and stripped.startswith("Interface "):
                current_interface = stripped.removeprefix("Interface ").strip()
                interfaces[current_interface] = (current_phy, None)
            elif current_interface is not None and stripped.startswith("type "):
                interfaces[current_interface] = (
                    interfaces[current_interface][0],
                    stripped.removeprefix("type ").strip(),
                )

        return interfaces

    def _link_is_up(self, interface: str) -> bool:
        result = self._run(
            ["ip", "-o", "link", "show", "dev", interface],
            capture_output=True,
        )
        match = re.search(r"<([^>]*)>", result.stdout)
        return match is not None and "UP" in match.group(1).split(",")

    def _network_manager_state(self, interface: str) -> bool | None:
        if shutil.which("nmcli") is None:
            return None
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        for field in ("GENERAL.NM-MANAGED", "GENERAL.MANAGED"):
            result = subprocess.run(
                ["nmcli", "-g", field, "device", "show", interface],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
                env=environment,
            )
            if result.returncode != 0:
                continue
            value = result.stdout.strip().lower()
            if value == "yes":
                return True
            if value == "no":
                return False
        return None

    def _set_managed(self, interface: str, managed: bool) -> None:
        if shutil.which("nmcli") is None:
            return
        self._run(
            [
                "nmcli",
                "device",
                "set",
                interface,
                "managed",
                "yes" if managed else "no",
            ]
        )

    def _save_and_disable_other_interfaces(
        self,
        interfaces: dict[str, tuple[str, str | None]],
    ) -> None:
        names = [
            name
            for name, (phy, _) in interfaces.items()
            if phy == self.phy and name != self.mon_iface
        ]
        self._saved_interfaces = [
            _InterfaceState(
                name=name,
                was_up=self._link_is_up(name),
                was_managed=self._network_manager_state(name),
            )
            for name in names
        ]

        for state in self._saved_interfaces:
            if state.was_managed:
                self._set_managed(state.name, False)
            if state.was_up:
                self._run(["ip", "link", "set", "dev", state.name, "down"])

    def _restore_interfaces(self) -> list[BaseException]:
        errors: list[BaseException] = []
        remaining: list[_InterfaceState] = []
        for state in self._saved_interfaces:
            try:
                if state.was_managed:
                    self._set_managed(state.name, True)
                if state.was_up:
                    self._run(["ip", "link", "set", "dev", state.name, "up"])
            except BaseException as error:
                errors.append(error)
                remaining.append(state)
        self._saved_interfaces = remaining
        return errors

    def _read_configured_channel(self) -> int | None:
        result = self._run(
            ["iw", "dev", self.mon_iface, "info"],
            capture_output=True,
        )
        for line in result.stdout.splitlines():
            fields = line.strip().split()
            if len(fields) >= 2 and fields[0] == "channel":
                try:
                    return int(fields[1])
                except ValueError:
                    return None
        return None

    def _supported_channels(self) -> set[int]:
        result = self._run(["iw", "phy", self.phy, "info"], capture_output=True)
        channels: set[int] = set()
        for line in result.stdout.splitlines():
            if "(disabled)" in line:
                continue
            match = re.search(r"\[(\d+)]", line)
            if match is not None:
                channels.add(int(match.group(1)))
        return channels

    def open(self) -> "LinuxMonitor":
        if self._is_open:
            raise RuntimeError("monitor interface is already open")
        self._hopping_error = None

        try:
            iw_result = self._run(["iw", "dev"], capture_output=True)
            interfaces = self._interfaces(iw_result.stdout)
            existing = interfaces.get(self.mon_iface)
            if existing is not None:
                existing_phy, existing_type = existing
                if existing_phy != self.phy:
                    raise RuntimeError(
                        f"{self.mon_iface!r} already exists on {existing_phy!r}"
                    )
                if not self.replace_existing:
                    raise RuntimeError(
                        f"{self.mon_iface!r} already exists; pass replace_existing=True "
                        "to replace it explicitly"
                    )
                if existing_type != "monitor":
                    raise RuntimeError(
                        f"refusing to replace {self.mon_iface!r}: its type is "
                        f"{existing_type!r}, not 'monitor'"
                    )

            self._save_and_disable_other_interfaces(interfaces)
            if existing is not None:
                self._run(["iw", "dev", self.mon_iface, "del"])

            self._run(
                [
                    "iw",
                    "phy",
                    self.phy,
                    "interface",
                    "add",
                    self.mon_iface,
                    "type",
                    "monitor",
                ]
            )
            self._owns_interface = True
            self._run(["ip", "link", "set", "dev", self.mon_iface, "up"])
            self._configured_channel = self._read_configured_channel()
            self.current_channel = self._configured_channel

            monitor_socket = socket.socket(
                socket.AF_PACKET,
                socket.SOCK_RAW,
                socket.htons(0x0003),
            )
            self._socket = monitor_socket
            monitor_socket.settimeout(self.socket_timeout)
            monitor_socket.bind((self.mon_iface, 0))
            self._is_open = True

            if self.initial_channel is not None:
                self.set_channel(self.initial_channel)
            return self
        except BaseException as original_error:
            cleanup_errors = self._cleanup()
            for cleanup_error in cleanup_errors:
                original_error.add_note(f"cleanup also failed: {cleanup_error!r}")
            raise

    def _cleanup(self) -> list[BaseException]:
        errors: list[BaseException] = []
        self._hopping_stop.set()
        thread = self._hopping_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self.command_timeout + 1)
            if thread.is_alive():
                errors.append(RuntimeError("channel hopping thread did not stop"))
        self._hopping_thread = None

        if self._socket is not None:
            try:
                self._socket.close()
            except BaseException as error:
                errors.append(error)
            self._socket = None

        if self._owns_interface:
            try:
                self._run(["iw", "dev", self.mon_iface, "del"])
            except BaseException as error:
                errors.append(error)
            else:
                self._owns_interface = False

        errors.extend(self._restore_interfaces())
        self._is_open = False
        self._configured_channel = None
        self.current_channel = None
        return errors

    def close(self) -> None:
        errors = self._cleanup()
        if errors:
            error = RuntimeError("failed to cleanly close monitor interface")
            for cleanup_error in errors:
                error.add_note(repr(cleanup_error))
            raise error from errors[0]

    def __enter__(self) -> "LinuxMonitor":
        return self.open()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            self.close()
        except BaseException as cleanup_error:
            if exc_value is None:
                raise
            exc_value.add_note(f"monitor cleanup failed: {cleanup_error!r}")
        return False

    def _require_open(self) -> None:
        if not self._is_open or self._socket is None:
            raise RuntimeError("monitor interface is not open")

    def set_channel(self, channel: int) -> None:
        self._require_open()
        if channel <= 0:
            raise ValueError("channel must be a positive integer")

        with self._channel_lock:
            if channel == self._configured_channel:
                return
            self._run(
                ["iw", "dev", self.mon_iface, "set", "channel", str(channel)]
            )
            self._configured_channel = channel
            self.current_channel = channel

    def _channel_hopping_loop(
        self,
        channels: tuple[int, ...],
        dwell_seconds: float,
    ) -> None:
        try:
            while not self._hopping_stop.is_set():
                for channel in channels:
                    if self._hopping_stop.is_set():
                        return
                    self.set_channel(channel)
                    if self._hopping_stop.wait(dwell_seconds):
                        return
        except BaseException as error:
            self._hopping_error = error
            self._hopping_stop.set()

    def start_channel_hopping(
        self,
        channels: Iterable[int],
        dwell_seconds: float = 0.25,
    ) -> None:
        self._require_open()
        channel_list = tuple(channels)
        if not channel_list:
            raise ValueError("channels must contain at least one channel")
        if any(channel <= 0 for channel in channel_list):
            raise ValueError("channels must contain only positive integers")
        if dwell_seconds <= 0:
            raise ValueError("dwell_seconds must be greater than zero")

        supported = self._supported_channels()
        unsupported = sorted(set(channel_list) - supported)
        if unsupported:
            raise ValueError(f"unsupported or disabled channels: {unsupported}")

        self.stop_channel_hopping()
        self._hopping_error = None
        self._hopping_stop.clear()
        self._hopping_thread = threading.Thread(
            target=self._channel_hopping_loop,
            args=(channel_list, dwell_seconds),
            name=f"{self.mon_iface}-channel-hopper",
            daemon=False,
        )
        self._hopping_thread.start()

    def stop_channel_hopping(self) -> None:
        thread = self._hopping_thread
        if thread is None:
            return
        self._hopping_stop.set()
        if thread is not threading.current_thread():
            thread.join(self.command_timeout + 1)
            if thread.is_alive():
                raise RuntimeError("channel hopping thread did not stop")
        self._hopping_thread = None

    def _raise_hopping_error(self) -> None:
        if self._hopping_error is None:
            return
        error = self._hopping_error
        self._hopping_error = None
        raise RuntimeError("channel hopping failed") from error

    def scan(self) -> tuple[bytes, int | None] | None:
        self._require_open()
        self._raise_hopping_error()
        assert self._socket is not None
        try:
            packet = self._socket.recvfrom(65535)[0]
        except TimeoutError:
            self._raise_hopping_error()
            return None
        except OSError as error:
            if error.errno != errno.ENETDOWN:
                raise
            self._raise_hopping_error()
            return None

        capture = extract_frame(packet)
        if capture is None:
            return None
        frame, channel = capture
        if channel is not None:
            self.current_channel = channel
        return frame, channel
