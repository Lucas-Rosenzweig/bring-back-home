from asyncio import sleep
import socket

from IEEE80211.IEEE80211Frame import IEEE80211Frame
from IEEE80211.IEEE80211FrameParser import IEEE80211FrameParser
from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame
from Wifi.LinuxMonitorInterface import LinuxMonitorInterface

monitor = LinuxMonitorInterface(mon_iface="mon0", phy="phy0")
try:
    while True:
        mac_frame = monitor.scan()
        if not mac_frame:
            continue

        try:
            mac_frame = IEEE80211FrameParser.parse(mac_frame)
            mac_frame.print()
        except NotImplementedError:
            continue
except KeyboardInterrupt:
    print("Supression de l'interface de monitoring et fermeture")
    monitor.delete()
