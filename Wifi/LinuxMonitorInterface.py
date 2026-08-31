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
    def _radiotap_header(packet: bytes) -> tuple[int, int, int] | None:
        """Return the header length, first presence word and fields offset."""
        if len(packet) < 8 or packet[0] != 0:
            return None

        header_length = int.from_bytes(packet[2:4], "little")
        if header_length < 8 or header_length > len(packet):
            return None

        presence_offset = 4
        first_presence_word: int | None = None
        while True:
            if presence_offset + 4 > header_length:
                return None

            presence_word = int.from_bytes(
                packet[presence_offset : presence_offset + 4],
                "little",
            )
            if first_presence_word is None:
                first_presence_word = presence_word

            presence_offset += 4
            if not presence_word & (1 << 31):
                break

        return header_length, first_presence_word, presence_offset

    @staticmethod
    def _frequency_to_channel(frequency: int) -> int | None:
        """Convert a Wi-Fi centre frequency in MHz to its channel number."""
        if frequency == 2484:
            return 14
        if 2412 <= frequency <= 2472 and (frequency - 2407) % 5 == 0:
            return (frequency - 2407) // 5
        if 4910 <= frequency <= 4980 and (frequency - 4000) % 5 == 0:
            return (frequency - 4000) // 5
        if 5000 <= frequency <= 5895 and (frequency - 5000) % 5 == 0:
            return (frequency - 5000) // 5
        if frequency == 5935:
            return 2
        if 5955 <= frequency <= 7115 and (frequency - 5950) % 5 == 0:
            return (frequency - 5950) // 5
        return None

    @classmethod
    def _channel_from_radiotap(cls, packet: bytes) -> int | None:
        """Extract the Wi-Fi channel from Radiotap's optional Channel field."""
        radiotap_header = cls._radiotap_header(packet)
        if radiotap_header is None:
            return None

        header_length, presence_word, fields_offset = radiotap_header
        if not presence_word & (1 << 3):
            return None

        field_layout = (
            (8, 8),  # TSFT
            (1, 1),  # Flags
            (1, 1),  # Rate
            (2, 4),  # Channel: frequency and flags
        )
        offset = fields_offset

        for index, (alignment, size) in enumerate(field_layout):
            if not presence_word & (1 << index):
                continue

            offset = (offset + alignment - 1) & -alignment
            if offset + size > header_length:
                return None

            if index == 3:
                frequency = int.from_bytes(packet[offset : offset + 2], "little")
                return cls._frequency_to_channel(frequency)

            offset += size

        return None

    @classmethod
    def _strip_radiotap(cls, packet: bytes) -> bytes | None:
        radiotap_header = cls._radiotap_header(packet)
        if radiotap_header is None:
            return None

        header_length, _, _ = radiotap_header
        return packet[header_length:] or None

    @override
    def scan(self) -> tuple[bytes, int | None] | None:
        """Return the 802.11 frame and its channel, when Radiotap exposes one."""
        if self.sock is None:
            raise RuntimeError("The monitor interface has been deleted")

        packet = self.sock.recvfrom(65535)[0]
        frame = self._strip_radiotap(packet)
        if frame is None:
            return None

        return frame, self._channel_from_radiotap(packet)
