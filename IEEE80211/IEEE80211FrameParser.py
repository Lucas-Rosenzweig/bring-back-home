from IEEE80211.header.IEEE80211FrameControl import IEEE80211FrameControl
from IEEE80211.header.IEEE80211FrameType import IEEE80211FrameType
from IEEE80211.IEEE80211Frame import IEEE80211Frame
from IEEE80211.IEEE80211ManagementFrame import IEEE80211ManagementFrame


class IEEE80211FrameParser:
    @staticmethod
    def parse(raw: bytes) -> IEEE80211Frame:
        frame_control = IEEE80211FrameControl(raw[:2])

        match frame_control.type:
            case IEEE80211FrameType.MANAGEMENT:
                return IEEE80211ManagementFrame(raw)
            case _:
                raise ValueError(
                    f"Unsupported frame type {frame_control.type}"
                )
