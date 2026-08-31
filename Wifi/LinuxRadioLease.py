"""Exclusive, reversible access to a Linux Wi-Fi PHY for LDN."""

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from Wifi.LinuxMonitor import LinuxMonitor


@dataclass(frozen=True, slots=True)
class _InterfaceState:
    name: str
    was_up: bool
    was_managed: bool | None


class LinuxRadioLease:
    """Keep NetworkManager away from one PHY and restore it on exit."""

    def __init__(
        self,
        phy: str,
        transient_interfaces: set[str],
        *,
        rule_path: Path = Path(
            "/etc/NetworkManager/conf.d/90-bring-back-home-ldn.conf"
        ),
        command_timeout: float = 5.0,
        settle_seconds: float = 1.0,
        require_root: bool = True,
    ) -> None:
        self.phy = phy
        self.transient_interfaces = set(transient_interfaces)
        self.rule_path = rule_path
        self.command_timeout = command_timeout
        self.settle_seconds = settle_seconds
        self.require_root = require_root
        self._saved_interfaces: list[_InterfaceState] = []
        self._rule_owned = False
        self._active = False

    def _run(
        self,
        command: list[str],
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

    def _link_is_up(self, interface: str) -> bool:
        result = self._run(
            ["ip", "-o", "link", "show", "dev", interface],
            capture_output=True,
        )
        match = re.search(r"<([^>]*)>", result.stdout)
        return match is not None and "UP" in match.group(1).split(",")

    def _managed_state(self, interface: str) -> bool | None:
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

    def _rule_content(self) -> str:
        names = ";".join(
            f"interface-name:{name}" for name in sorted(self.transient_interfaces)
        )
        return f"[keyfile]\nunmanaged-devices={names}\n"

    def _install_network_manager_rule(self) -> None:
        if shutil.which("nmcli") is None:
            return
        content = self._rule_content()
        if self.rule_path.exists():
            if self.rule_path.read_text(encoding="utf-8") != content:
                raise RuntimeError(
                    f"refusing to overwrite foreign NetworkManager rule "
                    f"{self.rule_path}"
                )
        else:
            self.rule_path.parent.mkdir(parents=True, exist_ok=True)
            self.rule_path.write_text(content, encoding="utf-8")
        self._rule_owned = True
        self._run(["nmcli", "general", "reload"])

    def _remove_network_manager_rule(self) -> None:
        if not self._rule_owned:
            return
        self.rule_path.unlink(missing_ok=True)
        self._rule_owned = False
        if shutil.which("nmcli") is not None:
            self._run(["nmcli", "general", "reload"])

    def _delete_transient_interfaces(self) -> None:
        for interface in sorted(self.transient_interfaces):
            if not Path("/sys/class/net", interface).exists():
                continue
            self._run(["iw", "dev", interface, "del"], check=False)
            if Path("/sys/class/net", interface).exists():
                self._run(["ip", "link", "del", interface], check=False)

    def open(self) -> Self:
        if self._active:
            raise RuntimeError("radio lease is already active")
        if self.require_root and os.geteuid() != 0:
            raise PermissionError("active LDN access must run as root")

        try:
            result = self._run(["iw", "dev"], capture_output=True)
            interfaces = LinuxMonitor._interfaces(result.stdout)
            names = [
                name
                for name, (phy, _) in interfaces.items()
                if phy == self.phy and name not in self.transient_interfaces
            ]
            self._saved_interfaces = [
                _InterfaceState(
                    name=name,
                    was_up=self._link_is_up(name),
                    was_managed=self._managed_state(name),
                )
                for name in names
            ]

            self._install_network_manager_rule()
            for state in self._saved_interfaces:
                if state.was_managed:
                    self._set_managed(state.name, False)
                if state.was_up:
                    self._run(["ip", "link", "set", "dev", state.name, "down"])
            self._delete_transient_interfaces()
            if self.settle_seconds > 0:
                time.sleep(self.settle_seconds)
            self._active = True
            return self
        except BaseException as original_error:
            for cleanup_error in self._cleanup():
                original_error.add_note(f"radio cleanup also failed: {cleanup_error!r}")
            raise

    def _cleanup(self) -> list[BaseException]:
        errors: list[BaseException] = []
        try:
            self._delete_transient_interfaces()
        except Exception as error:  # noqa: BLE001 - continue best-effort cleanup
            errors.append(error)
        try:
            self._remove_network_manager_rule()
        except Exception as error:  # noqa: BLE001 - continue best-effort cleanup
            errors.append(error)

        remaining: list[_InterfaceState] = []
        for state in self._saved_interfaces:
            try:
                if state.was_managed:
                    self._set_managed(state.name, True)
                if state.was_up:
                    self._run(["ip", "link", "set", "dev", state.name, "up"])
            except Exception as error:  # noqa: BLE001 - continue best-effort cleanup
                errors.append(error)
                remaining.append(state)
        self._saved_interfaces = remaining
        self._active = False
        return errors

    def close(self) -> None:
        errors = self._cleanup()
        if errors:
            error = RuntimeError("failed to restore the Wi-Fi PHY")
            for cleanup_error in errors:
                error.add_note(repr(cleanup_error))
            raise error from errors[0]

    def __enter__(self) -> Self:
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
            exc_value.add_note(f"radio cleanup failed: {cleanup_error!r}")
        return False
