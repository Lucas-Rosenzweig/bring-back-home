from abc import ABC, abstractmethod

from IEEE80211Frame.FrameControl import FrameControl


class IEEE80211Header(ABC):
    raw: bytes
    frame_control: FrameControl

    def __init__(self, raw: bytes) -> None:
        if len(raw) < 2:
            raise ValueError("Header too short")

        self.raw = raw
        self.frame_control = FrameControl(raw[:2])

    @abstractmethod
    def parse(self) -> None:
        pass
