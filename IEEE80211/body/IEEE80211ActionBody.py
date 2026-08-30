from typing import override

from IEEE80211.body.IEEE80211Body import IEEE80211Body
from IEEE80211.body.action.IEEE80211Action import IEEE80211Action
from IEEE80211.body.action.IEEE80211ActionCategory import IEEE80211ActionCategory
from IEEE80211.body.action.IEEE80211VendorSpecificAction import IEEE80211VendorSpecificAction
from IEEE80211.body.action.UnknownIEEE80211Action import UnknownIEEE80211Action


class IEEE80211ActionBody(IEEE80211Body):
    category: bytes
    action_data: bytes
    action: IEEE80211Action

    def __init__(self, raw: bytes) -> None:
        super().__init__(raw)
        self.parse()

    @override
    def parse(self) -> None:
        if not self.raw:
            raise ValueError("Action body must contain a category")

        self.category = self.raw[0:1]
        self.action_data = self.raw[1:]

        if self.category == IEEE80211ActionCategory.VENDOR_SPECIFIC.value:
            self.action = IEEE80211VendorSpecificAction(self.action_data)
        else:
            self.action = UnknownIEEE80211Action(self.action_data)

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Action Body:")
        print(f"{field_indent}Category           : 0x{self.category.hex().upper()}")
        print(f"{field_indent}Action Data:")
        self.action.print(f"{field_indent}  ")
