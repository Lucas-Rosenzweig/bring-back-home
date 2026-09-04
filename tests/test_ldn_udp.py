from __future__ import annotations

import socket
import struct
import unittest

from pokemon_trade.transport.ldn_udp import _parse_ethernet_ipv4_udp


def ethernet_udp(
    payload: bytes,
    *,
    source: str = "169.254.1.1",
    destination: str = "169.254.1.255",
    source_port: int = 12345,
    destination_port: int = 12345,
) -> bytes:
    udp = struct.pack("!HHHH", source_port, destination_port, 8 + len(payload), 0) + payload
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (20 + len(udp)).to_bytes(2, "big")
    ip[8] = 64
    ip[9] = socket.IPPROTO_UDP
    ip[12:16] = socket.inet_aton(source)
    ip[16:20] = socket.inet_aton(destination)
    return bytes.fromhex("ffffffffffff0200000000010800") + bytes(ip) + udp


class LdnUdpFrameTest(unittest.TestCase):
    def test_extracts_a_complete_broadcast_udp_datagram(self) -> None:
        parsed = _parse_ethernet_ipv4_udp(ethernet_udp(b"pia"))

        self.assertEqual(
            parsed,
            (("169.254.1.1", 12345), ("169.254.1.255", 12345), b"pia"),
        )

    def test_ignores_truncated_wrong_protocol_and_invalid_lengths(self) -> None:
        frame = ethernet_udp(b"pia")
        self.assertIsNone(_parse_ethernet_ipv4_udp(frame[:30]))
        wrong_protocol = bytearray(frame)
        wrong_protocol[14 + 9] = socket.IPPROTO_TCP
        self.assertIsNone(_parse_ethernet_ipv4_udp(bytes(wrong_protocol)))
        wrong_length = bytearray(frame)
        wrong_length[14 + 20 + 4 : 14 + 20 + 6] = (999).to_bytes(2, "big")
        self.assertIsNone(_parse_ethernet_ipv4_udp(bytes(wrong_length)))
