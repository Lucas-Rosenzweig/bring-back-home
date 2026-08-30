from IEEE80211Frame.header.IEEE80211Header import IEEE80211Header


class IEEE80211ManagementHeader(IEEE80211Header):
    duration: bytes #0x02
    address1: bytes #0x04
    address2: bytes #0x0A
    address3: bytes #0x10
    sequence_controll: bytes #0x16

    MANAGEMENT_HEADER_SIZE = 24


    def __init__(self, raw: bytes) -> None:
        super().__init__(raw)
        self.parse()

    def parse(self) -> None:
        if len(self.raw) != self.MANAGEMENT_HEADER_SIZE:
            raise ValueError("Management header should be 24 bytes long")

        self.duration = self.raw[2:4]
        self.address1 = self.raw[4:10]
        self.address2 = self.raw[10:16]
        self.address3 = self.raw[16:22]
        self.sequence_controll = self.raw[22:24]

    def print(self) -> None:
        print("Implémenter le print de Management header")
