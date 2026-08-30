from IEEE80211Frame.body.IEEE80211Body import IEEE80211Body


class IEEE80211ActionBody(IEEE80211Body):
    category: int
    action_data: bytes
    def __init__(self, raw: bytes) -> None:
        super().__init__(raw)
        self.parse()

    def parse(self) -> None:
        if not self.raw:
            raise ValueError("Action body must contain a category")

        self.category = self.raw[0]
        self.action_data = self.raw[1:]
