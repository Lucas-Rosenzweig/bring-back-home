from enum import Enum


class NintendoLdnAdvertisementFormat(Enum):
    PLAIN = b"\x01"
    AES_CTR = b"\x02"
    AES_GCM = b"\x03"
