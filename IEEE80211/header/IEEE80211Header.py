from abc import ABC, abstractmethod

from IEEE80211.header.IEEE80211FrameControl import IEEE80211FrameControl


class IEEE80211Header(ABC):
    raw: bytes
    frame_control: IEEE80211FrameControl

    def __init__(self, raw: bytes) -> None:
        if len(raw) < 2:
            raise ValueError("Header too short")

        self.raw = raw
        self.frame_control = IEEE80211FrameControl(raw[:2])

    @abstractmethod
    def parse(self) -> None:
        pass

    @abstractmethod
    def print(self, indent: str = "") -> None:
        pass
