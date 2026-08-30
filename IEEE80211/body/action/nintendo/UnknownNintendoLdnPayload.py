from typing import override

from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload


class UnknownNintendoLdnPayload(NintendoLdnPayload):
    data: bytes

    @override
    def parse(self) -> None:
        self.data = self.raw

    @override
    def print(self, indent: str = "") -> None:
        print(f"{indent}Unknown Nintendo LDN Payload:")
        print(f"{indent}  Raw Data           : {self.data.hex(' ')}")
