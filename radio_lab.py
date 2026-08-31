from IEEE80211.IEEE80211FrameParser import IEEE80211FrameParser
from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame
from IEEE80211.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211.body.action.IEEE80211Action import IEEE80211Action
from IEEE80211.body.action.IEEE80211VendorAction import IEEE80211VendorAction
from IEEE80211.body.action.IEEE80211VendorSpecificAction import IEEE80211VendorSpecificAction
from IEEE80211.body.action.nintendo.NintendoLdnAction import NintendoLdnAction
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisement import NintendoLdnAdvertisement
from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload
from Wifi.LinuxMonitorInterface import LinuxMonitorInterface

monitor = LinuxMonitorInterface(mon_iface="mon0", phy="phy0")
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

            print("Advertisement trouvé sur le channel",channel,"!")
            print("Changement de channel")
            monitor.set_channel(channel)
        except NotImplementedError:
            continue
except KeyboardInterrupt:
    print("Supression de l'interface de monitoring et fermeture")
    monitor.delete()
