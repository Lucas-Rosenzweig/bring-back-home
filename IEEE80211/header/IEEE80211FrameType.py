from enum import IntEnum


class IEEE80211FrameType(IntEnum):
    MANAGEMENT = 0
    CONTROL = 1
    DATA = 2
    EXTENSION = 3
