"""UDP adapter over an already-established project-owned LDN connection."""

from __future__ import annotations

import socket
import struct
import time
from typing import TYPE_CHECKING

import trio

from pokemon_trade.errors import MalformedDatagramError
from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext

if TYPE_CHECKING:
    from Wifi.LdnStation import LdnConnection


class LdnUdpTransport:
    """Expose only LDN session facts and UDP datagrams to a game plugin."""

    def __init__(
        self,
        session: SessionContext,
        receiver: socket.socket,
        raw_receiver: socket.socket,
        *,
        port: int = 12345,
    ) -> None:
        self.session = session
        self._receiver = receiver
        self._raw_receiver = raw_receiver
        self._port = port
        self._closed = False

    @classmethod
    async def open(
        cls,
        connection: LdnConnection,
        interface: str,
        *,
        port: int = 12345,
    ) -> LdnUdpTransport:
        if not 1 <= port <= 65535:
            raise ValueError("UDP port must be between 1 and 65535")
        network = connection.info()
        local = connection.participant()
        host = network.participants[0]
        context = SessionContext(
            ssid=bytes(network.ssid),
            communication_id=int(network.local_communication_id),
            scene_id=int(network.scene_id),
            app_version=int(network.app_version),
            interface=interface,
            local=ParticipantAddress(local.ip_address, str(local.mac_address)),
            host=ParticipantAddress(host.ip_address, str(host.mac_address)),
            broadcast_address=connection.broadcast_address(),
        )
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw_receiver: socket.socket | None = None
        try:
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            receiver.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                interface.encode("ascii") + b"\0",
            )
            receiver.bind(("0.0.0.0", port))
            receiver.setblocking(False)
            # AX200/iwlmvm can associate and authenticate an LDN station
            # without reinjecting broadcast UDP into the normal IP socket.
            # Receive the already-decapsulated Ethernet frames instead; TX
            # remains an ordinary UDP socket owned by the LDN interface.
            raw_receiver = socket.socket(
                socket.AF_PACKET,
                socket.SOCK_RAW,
                socket.htons(0x0800),  # ETH_P_IP
            )
            raw_receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            raw_receiver.bind((interface, 0))
            raw_receiver.setblocking(False)
        except BaseException:
            receiver.close()
            if raw_receiver is not None:
                raw_receiver.close()
            raise
        assert raw_receiver is not None
        return cls(context, receiver, raw_receiver, port=port)

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        self._ensure_open()
        self._validate_destination(destination)
        if not payload:
            raise MalformedDatagramError("refusing to send an empty UDP datagram")
        while True:
            try:
                self._receiver.sendto(payload, destination)
                return
            except BlockingIOError:
                await trio.lowlevel.wait_writable(self._receiver.fileno())

    async def receive(self) -> Datagram:
        self._ensure_open()
        while True:
            await trio.lowlevel.wait_readable(self._raw_receiver.fileno())
            try:
                frame = self._raw_receiver.recv(65535)
            except BlockingIOError:
                continue
            parsed = _parse_ethernet_ipv4_udp(frame)
            if parsed is None:
                continue
            source, destination, payload = parsed
            if source[0] == self.session.local.ip_address:
                continue
            if source != (self.session.host.ip_address, self._port):
                continue
            if destination[1] != self._port or destination[0] not in {
                self.session.local.ip_address,
                self.session.broadcast_address,
                "255.255.255.255",
            }:
                continue
            if not payload:
                raise MalformedDatagramError("received an empty UDP datagram")
            return Datagram(
                payload,
                source,
                destination,
                time.monotonic(),
            )

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._receiver.close()
            self._raw_receiver.close()

    def _validate_destination(self, destination: tuple[str, int]) -> None:
        host, port = destination
        if port != self._port or host not in {
            self.session.host.ip_address,
            self.session.broadcast_address,
        }:
            raise MalformedDatagramError("destination is outside the LDN session")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("LDN UDP transport is closed")


def _parse_ethernet_ipv4_udp(
    frame: bytes,
) -> tuple[tuple[str, int], tuple[str, int], bytes] | None:
    """Return one complete Ethernet/IPv4/UDP datagram, or ignore unrelated L2 traffic."""
    if len(frame) < 14 + 20 + 8 or struct.unpack_from("!H", frame, 12)[0] != 0x0800:
        return None
    ip_header = frame[14:]
    version_ihl = ip_header[0]
    header_size = (version_ihl & 0x0F) * 4
    if version_ihl >> 4 != 4 or header_size < 20 or len(ip_header) < header_size + 8:
        return None
    total_size = struct.unpack_from("!H", ip_header, 2)[0]
    if total_size < header_size + 8 or total_size > len(ip_header) or ip_header[9] != socket.IPPROTO_UDP:
        return None
    udp = ip_header[header_size:total_size]
    source_port, destination_port, udp_size = struct.unpack_from("!HHH", udp)
    if udp_size < 8 or udp_size > len(udp):
        return None
    source = socket.inet_ntoa(ip_header[12:16])
    destination = socket.inet_ntoa(ip_header[16:20])
    return (source, source_port), (destination, destination_port), bytes(udp[8:udp_size])
