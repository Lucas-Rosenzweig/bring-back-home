from abc import ABC, abstractmethod

from IEEE80211Frame.body.IEEE80211Body import IEEE80211Body
from IEEE80211Frame.header.IEEE80211Header import IEEE80211Header;

class IEEE80211Frame(ABC):
    raw: bytes
    header: IEEE80211Header
    body: IEEE80211Body

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    @abstractmethod
    def parse(self) -> None:
        pass

    @abstractmethod
    def print(self, indent: str = "") -> None:
        pass
