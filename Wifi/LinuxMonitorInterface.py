import errno
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterable
from typing import override

from Wifi.WifiInterface import WifiInterface


class LinuxMonitorInterface(WifiInterface):
    """Linux monitor-mode interface backed by ``iw`` and an AF_PACKET socket."""

    def __init__(
        self,
        mon_iface: str = "mon0",
        phy: str = "phy0",
        initial_channel: int | None = None,
    ) -> None:
        self.mon_iface: str = mon_iface
        self.phy: str = phy
        self._created_interface: bool = False
        self._configured_channel: int | None = None
        self.current_channel: int | None = None
        self._channel_lock: threading.Lock = threading.Lock()
        self._hopping_stop: threading.Event = threading.Event()
        self._hopping_thread: threading.Thread | None = None
        self.hopping_error: subprocess.CalledProcessError | None = None
        self.sock: socket.socket | None = None

        self.create()
        if initial_channel is not None:
            self.set_channel(initial_channel)

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

    @staticmethod
    def _interfaces_on_phy(iw_dev_output: str, phy: str) -> list[str]:
        """Return network interfaces associated with ``phy`` in ``iw dev`` output."""
        current_phy: str | None = None
        interfaces: list[str] = []

        for line in iw_dev_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("phy#"):
                current_phy = f"phy{stripped.removeprefix('phy#')}"
            elif current_phy == phy and stripped.startswith("Interface "):
                interfaces.append(stripped.removeprefix("Interface ").strip())

        return interfaces

    @staticmethod
    def _unmanage_with_network_manager(interface: str) -> None:
        """Detach an interface from NetworkManager when it is available."""
        if shutil.which("nmcli") is None:
            return

        _ = subprocess.run(
            ["nmcli", "device", "set", interface, "managed", "no"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _disable_other_interfaces(self, iw_dev_output: str) -> None:
        """Release this phy by unmanaging and taking down other interfaces."""
        for interface in self._interfaces_on_phy(iw_dev_output, self.phy):
            if interface != self.mon_iface:
                self._unmanage_with_network_manager(interface)
                _ = subprocess.run(
                    ["ip", "link", "set", "dev", interface, "down"],
                    check=True,
                )

    def _read_configured_channel(self) -> int | None:
        """Return the channel currently reported by ``iw`` for the monitor interface."""
        result = subprocess.run(
            ["iw", "dev", self.mon_iface, "info"],
            check=True,
            capture_output=True,
            text=True,
        )

        for line in result.stdout.splitlines():
            fields = line.strip().split()
            if len(fields) >= 2 and fields[0] == "channel":
                try:
                    return int(fields[1])
                except ValueError:
                    return None

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
        """Reserve the phy for the monitor interface, create it and bring it up."""
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

        self._disable_other_interfaces(result.stdout)
        _ = subprocess.run(
            ["ip", "link", "set", "dev", self.mon_iface, "up"],
            check=True,
        )
        self._configured_channel = self._read_configured_channel()

    @override
    def delete(self) -> None:
        """Stop hopping, close the socket and delete an owned interface."""
        self.stop_channel_hopping()
        self._close_socket()
        if self._created_interface:
            self._delete_interface()

    @override
    def set_channel(self, channel: int) -> None:
        """Set the monitor interface channel, temporarily taking it down."""
        if channel <= 0:
            raise ValueError("channel must be a positive integer")

        with self._channel_lock:
            if self._configured_channel is None:
                self._configured_channel = self._read_configured_channel()
            if channel == self._configured_channel:
                return

            result = subprocess.run(
                ["iw", "dev"],
                check=True,
                capture_output=True,
                text=True,
            )
            self._disable_other_interfaces(result.stdout)
            _ = subprocess.run(
                ["ip", "link", "set", "dev", self.mon_iface, "down"],
                check=True,
            )
            try:
                _ = subprocess.run(
                    ["iw", "dev", self.mon_iface, "set", "channel", str(channel)],
                    check=True,
                )
            finally:
                _ = subprocess.run(
                    ["ip", "link", "set", "dev", self.mon_iface, "up"],
                    check=True,
                )

            self._configured_channel = channel

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
        except subprocess.CalledProcessError as error:
            self.hopping_error = error
            self._hopping_stop.set()

    def start_channel_hopping(
        self,
        channels: Iterable[int],
        dwell_seconds: float = 0.25,
    ) -> None:
        """Continuously cycle through channels in a background thread."""
        channel_list = tuple(channels)
        if not channel_list:
            raise ValueError("channels must contain at least one channel")
        if any(channel <= 0 for channel in channel_list):
            raise ValueError("channels must contain only positive integers")
        if dwell_seconds <= 0:
            raise ValueError("dwell_seconds must be greater than zero")

        self.stop_channel_hopping()
        self.hopping_error = None
        self._hopping_stop.clear()
        self._hopping_thread = threading.Thread(
            target=self._channel_hopping_loop,
            args=(channel_list, dwell_seconds),
            name=f"{self.mon_iface}-channel-hopper",
            daemon=True,
        )
        self._hopping_thread.start()

    def stop_channel_hopping(self) -> None:
        """Stop the background channel-hopping thread, if it is running."""
        thread = self._hopping_thread
        if thread is None:
            return

        self._hopping_stop.set()
        if thread is not threading.current_thread():
            thread.join()
        self._hopping_thread = None

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

        try:
            packet = self.sock.recvfrom(65535)[0]
        except OSError as error:
            if error.errno != errno.ENETDOWN:
                raise
            time.sleep(0.01)
            return None

        frame = self._strip_radiotap(packet)
        if frame is None:
            return None

        channel = self._channel_from_radiotap(packet)
        if channel is not None:
            self.current_channel = channel

        return frame, channel
