import socket

from IEEE80211.IEEE80211Frame import IEEE80211Frame
from IEEE80211.IEEE80211FrameParser import IEEE80211FrameParser
from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame

sock = socket.socket(
    socket.AF_PACKET,
    socket.SOCK_RAW,
    socket.htons(0x0003),
)

sock.bind(("mon0", 0))

def strip_radiotap(packet: bytes) -> bytes | None:

    if len(packet) < 4:
        return None

    radiotap_length = int.from_bytes(packet[2:4],"little")

    if len(packet) <= radiotap_length + 2:
        return None

    return packet[radiotap_length:]

while True:
    packet, _ = sock.recvfrom(65535)

    #Strip radiotap header
    mac_frame = strip_radiotap(packet)
    if not mac_frame:
        continue

    try:
        mac_frame = IEEE80211FrameParser.parse(mac_frame)
        mac_frame.print()
    except NotImplementedError:
        continue
