from typing import override

from IEEE80211.body.action.IEEE80211Action import IEEE80211Action


class UnknownIEEE80211Action(IEEE80211Action):
    data: bytes

    @override
    def parse(self) -> None:
        self.data = self.raw

    @override
    def print(self, indent: str = "") -> None:
        print(f"{indent}Unknown Action:")
        print(f"{indent}  Raw Data           : {self.data.hex(' ')}")
