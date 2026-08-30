import socket

from IEEE80211Frame.FrameControl import FrameControl

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

    print(int.from_bytes(mac_frame[2:4],"little"))
    frame_control = FrameControl(mac_frame[0:2])
    if(frame_control.type == 0 and frame_control.subtype == 13):
        frame_control.print()
