from typing import ClassVar, override

from IEEE80211.body.action.IEEE80211Action import IEEE80211Action
from IEEE80211.body.action.IEEE80211VendorAction import IEEE80211VendorAction
from IEEE80211.body.action.UnknownVendorAction import UnknownVendorAction
from IEEE80211.body.action.nintendo.NintendoLdnAction import NintendoLdnAction


class IEEE80211VendorSpecificAction(IEEE80211Action):
    NINTENDO_OUI: ClassVar[bytes] = b"\x00\x22\xAA"

    oui: bytes
    vendor_data: bytes
    vendor_action: IEEE80211VendorAction

    @override
    def parse(self) -> None:
        if len(self.raw) < 3:
            raise ValueError("Vendor-specific action must contain a 3-byte OUI")

        self.oui = self.raw[0:3]
        self.vendor_data = self.raw[3:]

        if self.oui == self.NINTENDO_OUI and self.vendor_data[:1] == b"\x04":
            self.vendor_action = NintendoLdnAction(self.vendor_data)
        else:
            self.vendor_action = UnknownVendorAction(self.vendor_data)

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Vendor-Specific Action:")
        print(f"{field_indent}OUI                 : {self.oui.hex(':')}")
        self.vendor_action.print(field_indent)
