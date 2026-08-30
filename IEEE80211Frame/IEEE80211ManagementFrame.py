from IEEE80211Frame.IEEE80211Frame import IEEE80211Frame
from IEEE80211Frame.body.IEEE80211ActionBody import IEEE80211ActionBody
from IEEE80211Frame.header.IEEE80211ManagementHeader import IEEE80211ManagementHeader


class IEEE80211ManagementFrame(IEEE80211Frame):
    def __init__(self, raw: bytes) -> None:
        super().__init__(raw)
        self.parse()

    def parse(self) -> None:
        self.header = IEEE80211ManagementHeader(self.raw)

        subtype = self.header.frame_control.subtype

        if subtype == 13: #Action Frame
            self.body = IEEE80211ActionBody(self.raw[IEEE80211ManagementHeader.MANAGEMENT_HEADER_SIZE:])
        else:
            raise NotImplementedError(
                f"Unsupported management subtype {subtype}"
            )
