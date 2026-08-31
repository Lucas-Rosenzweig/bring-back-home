from IEEE80211.IEEE80211FrameParser import IEEE80211FrameParser
from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame
from IEEE80211.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211.body.action.IEEE80211VendorSpecificAction import IEEE80211VendorSpecificAction
from IEEE80211.body.action.nintendo.NintendoLdnAction import NintendoLdnAction
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisement import NintendoLdnAdvertisement
from Wifi.LinuxMonitorInterface import LinuxMonitorInterface

LDN_CHANNELS = (1, 6, 11, 36, 40, 44, 48)
LDN_DWELL_SECONDS = 0.110

monitor = LinuxMonitorInterface(
    mon_iface="mon0",
    phy="phy0",
    initial_channel=LDN_CHANNELS[0],
)
monitor.start_channel_hopping(LDN_CHANNELS, dwell_seconds=LDN_DWELL_SECONDS)

try:
    while True:
        capture = monitor.scan()
        if capture is None:
            continue

        mac_frame, channel = capture
        if not channel:
            continue

        try:
            mac_frame = IEEE80211FrameParser.parse(mac_frame)

            if  not isinstance(mac_frame, IEEE80211ManagementFrame):
                continue

            if not isinstance(mac_frame.body, IEEE80211ActionBody):
                continue

            if not isinstance(mac_frame.body.action, IEEE80211VendorSpecificAction):
                continue

            if not isinstance(mac_frame.body.action.vendor_action, NintendoLdnAction):
                continue

            if not isinstance(mac_frame.body.action.vendor_action.payload, NintendoLdnAdvertisement):
                continue

            print("Advertisement trouvé sur le channel", channel, "!")
        except (NotImplementedError, ValueError):
            continue
except KeyboardInterrupt:
    print("Supression de l'interface de monitoring et fermeture")
    monitor.delete()
