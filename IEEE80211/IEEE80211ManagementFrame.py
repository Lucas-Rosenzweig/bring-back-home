from enum import IntEnum
from typing import ClassVar, override

from IEEE80211.IEEE80211Frame import IEEE80211Frame
from IEEE80211.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211.header.IEEE80211ManagementHeader import IEEE80211ManagementHeader


class ManagementSubtype(IntEnum):
    ACTION = 13


class IEEE80211ManagementFrame(IEEE80211Frame):
    MANAGEMENT_FRAME_TYPE: ClassVar[int] = 0

    def __init__(self, raw: bytes) -> None:
        super().__init__(raw)
        self.parse()

    @override
    def parse(self) -> None:
        header_size = IEEE80211ManagementHeader.MANAGEMENT_HEADER_SIZE
        self.header = IEEE80211ManagementHeader(self.raw[:header_size])

        if self.header.frame_control.type != self.MANAGEMENT_FRAME_TYPE:
            raise ValueError("Frame is not a management frame")

        subtype = self.header.frame_control.subtype
        body_raw = self.raw[header_size:]

        match subtype:
            case ManagementSubtype.ACTION:
                self.body = IEEE80211ActionBody(body_raw)
            case _:
                raise NotImplementedError(
                    f"Unsupported management subtype {subtype}"
                )

    @override
    def print(self, indent: str = "") -> None:
        component_indent = f"{indent}  "
        print(f"{indent}IEEE 802.11 Management Frame:")
        self.header.print(component_indent)
        self.body.print(component_indent)
