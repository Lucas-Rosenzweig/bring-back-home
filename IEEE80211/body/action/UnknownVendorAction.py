from typing import override

from IEEE80211.body.action.IEEE80211VendorAction import IEEE80211VendorAction


class UnknownVendorAction(IEEE80211VendorAction):
    data: bytes

    @override
    def parse(self) -> None:
        self.data = self.raw

    @override
    def print(self, indent: str = "") -> None:
        print(f"{indent}Unknown Vendor Action:")
        print(f"{indent}  Raw Data           : {self.data.hex(' ')}")
