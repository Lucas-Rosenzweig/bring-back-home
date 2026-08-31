import socket
import subprocess
from typing import override

from Wifi.WifiInterface import WifiInterface


class LinuxMonitorInterface(WifiInterface):
    """Linux monitor-mode interface backed by ``iw`` and an AF_PACKET socket."""

    def __init__(
        self,
        mon_iface: str = "mon0",
        phy: str = "phy0",
    ) -> None:
        self.mon_iface: str = mon_iface
        self.phy: str = phy
        self._created_interface: bool = False
        self.sock: socket.socket | None = None

        self.create()
        try:
            self.sock = socket.socket(
                socket.AF_PACKET,
                socket.SOCK_RAW,
                socket.htons(0x0003),
            )
            self.sock.bind((self.mon_iface, 0))
        except BaseException:
            self._close_socket()
            if self._created_interface:
                self._delete_interface()
            raise

    @staticmethod
    def _interface_phy(iw_dev_output: str, interface: str) -> str | None:
        """Return the phy owning an interface listed by ``iw dev``."""
        current_phy: str | None = None

        for line in iw_dev_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("phy#"):
                current_phy = f"phy{stripped.removeprefix('phy#')}"
            elif (
                current_phy is not None
                and stripped.startswith("Interface ")
                and stripped.removeprefix("Interface ").strip() == interface
            ):
                return current_phy

        return None

    def _delete_interface(self) -> None:
        _ = subprocess.run(
            ["iw", "dev", self.mon_iface, "del"],
            check=True,
        )
        self._created_interface = False

    def _close_socket(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    @override
    def create(self) -> None:
        """Create the monitor interface when needed and bring it up."""
        result = subprocess.run(
            ["iw", "dev"],
            check=True,
            capture_output=True,
            text=True,
        )
        existing_phy = self._interface_phy(result.stdout, self.mon_iface)

        if existing_phy is None:
            _ = subprocess.run(
                [
                    "iw",
                    "phy",
                    self.phy,
                    "interface",
                    "add",
                    self.mon_iface,
                    "type",
                    "monitor",
                ],
                check=True,
            )
            self._created_interface = True
        elif existing_phy != self.phy:
            raise RuntimeError(
                f"Interface {self.mon_iface!r} already exists on {existing_phy!r}, "
                + f"not {self.phy!r}"
            )

        _ = subprocess.run(
            ["ip", "link", "set", "dev", self.mon_iface, "up"],
            check=True,
        )

    @override
    def delete(self) -> None:
        """Close the capture socket and delete an interface created by this object."""
        self._close_socket()
        if self._created_interface:
            self._delete_interface()

    @override
    def set_channel(self, channel: int) -> None:
        """Set the monitor interface channel."""
        if channel <= 0:
            raise ValueError("channel must be a positive integer")

        _ = subprocess.run(
            ["iw", "dev", self.mon_iface, "set", "channel", str(channel)],
            check=True,
        )

    @staticmethod
    def _strip_radiotap(packet: bytes) -> bytes | None:
        if len(packet) < 8:
            return None

        radiotap_length = int.from_bytes(packet[2:4], "little")
        if radiotap_length < 8 or radiotap_length > len(packet):
            return None

        return packet[radiotap_length:] or None

    @override
    def scan(self) -> bytes | None:
        """Block until a packet is received, then remove its Radiotap header."""
        if self.sock is None:
            raise RuntimeError("The monitor interface has been deleted")

        packet = self.sock.recvfrom(65535)[0]
        return self._strip_radiotap(packet)
