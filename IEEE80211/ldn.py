"""Parser for the Nintendo LDN advertisement frames used by the radio lab."""

import sys
from dataclasses import dataclass
from string import printable
from typing import TextIO

VENDOR_SPECIFIC_CATEGORY = 0x7F
NINTENDO_OUI = b"\x00\x22\xaa"
LDN_PROTOCOL_ID = 0x04
ADVERTISEMENT_PACKET_TYPE = b"\x01\x01"

PLAIN = 0x01
AES_CTR = 0x02
AES_GCM = 0x03


@dataclass(frozen=True, slots=True)
class LdnAdvertisement:
    raw_frame: bytes
    session_info: bytes
    ldn_version: int
    encryption_type: int
    data_size: int
    nonce: bytes
    advertisement_data: bytes
    authentication_tag: bytes | None = None
    integrity_hash: bytes | None = None
    trailing_data: bytes = b""

    @property
    def is_encrypted(self) -> bool:
        return self.encryption_type in {AES_CTR, AES_GCM}

    @property
    def local_communication_id(self) -> int:
        return int.from_bytes(self.session_info[:8], "big")

    @property
    def scene_id(self) -> int:
        return int.from_bytes(self.session_info[10:12], "big")

    @property
    def ssid(self) -> bytes:
        return self.session_info[16:32]

    def display(self, file: TextIO | None = None) -> None:
        """Print a readable view of the captured 802.11 LDN frame."""
        output = file if file is not None else sys.stdout
        format_name = {
            PLAIN: "PLAIN",
            AES_CTR: "AES_CTR",
            AES_GCM: "AES_GCM",
        }.get(self.encryption_type, "UNKNOWN")
        ascii_data = "".join(
            character if character in printable and character.isprintable() else "."
            for character in map(chr, self.advertisement_data)
        )
        lines = [
            "Nintendo LDN advertisement:",
            f"  Frame control      : {self.raw_frame[:2].hex(' ')}",
            f"  Destination        : {self.raw_frame[4:10].hex(':')}",
            f"  Source             : {self.raw_frame[10:16].hex(':')}",
            f"  BSSID              : {self.raw_frame[16:22].hex(':')}",
            f"  Communication ID   : 0x{self.local_communication_id:016X}",
            f"  Scene ID           : {self.scene_id}",
            f"  SSID               : {self.ssid.hex()}",
            f"  LDN version        : 0x{self.ldn_version:02X}",
            f"  Encryption         : {format_name} (0x{self.encryption_type:02X})",
            f"  Declared data size : {self.data_size} bytes",
            f"  Nonce              : {self.nonce.hex(' ')}",
        ]
        if self.authentication_tag is not None:
            lines.append(f"  Authentication tag : {self.authentication_tag.hex(' ')}")
        if self.integrity_hash is not None:
            lines.append(f"  Integrity hash     : {self.integrity_hash.hex(' ')}")
        lines.extend(
            (
                f"  Advertisement data : {self.advertisement_data.hex(' ')}",
                f"  ASCII preview      : {ascii_data}",
            )
        )
        if self.trailing_data:
            lines.append(f"  Trailing data      : {self.trailing_data.hex(' ')}")
        lines.append(f"  Raw frame          : {self.raw_frame.hex(' ')}")
        print("\n".join(lines), file=output)


def _parse_payload(payload: bytes, raw_frame: bytes) -> LdnAdvertisement:
    if len(payload) < 40:
        raise ValueError("Nintendo LDN advertisement has a truncated header")

    session_info = payload[:32]
    ldn_version = payload[32]
    encryption_type = payload[33]
    data_size = int.from_bytes(payload[34:36], "big")
    nonce = payload[36:40]
    authentication_tag: bytes | None = None
    integrity_hash: bytes | None = None

    if encryption_type == AES_GCM:
        data_offset = 56
        if len(payload) < data_offset:
            raise ValueError("Nintendo LDN advertisement has a truncated GCM tag")
        authentication_tag = payload[40:data_offset]
        data_end = data_offset + data_size
    elif encryption_type == PLAIN:
        data_offset = 72
        if len(payload) < data_offset:
            raise ValueError(
                "Nintendo LDN advertisement has a truncated integrity hash"
            )
        integrity_hash = payload[40:data_offset]
        data_end = data_offset + data_size
    elif encryption_type == AES_CTR:
        data_offset = 40
        data_end = data_offset + 32 + data_size
    else:
        data_offset = 40
        data_end = len(payload)

    if len(payload) < data_end:
        raise ValueError("Nintendo LDN advertisement has truncated data")

    return LdnAdvertisement(
        raw_frame=raw_frame,
        session_info=session_info,
        ldn_version=ldn_version,
        encryption_type=encryption_type,
        data_size=data_size,
        nonce=nonce,
        advertisement_data=payload[data_offset:data_end],
        authentication_tag=authentication_tag,
        integrity_hash=integrity_hash,
        trailing_data=payload[data_end:],
    )


def parse_ldn_advertisement(frame: bytes) -> LdnAdvertisement | None:
    """Parse an LDN advertisement, or return ``None`` for unrelated traffic."""
    if len(frame) < 25:
        return None

    frame_control = int.from_bytes(frame[:2], "little")
    frame_type = (frame_control >> 2) & 0b11
    subtype = (frame_control >> 4) & 0b1111
    if frame_type != 0 or subtype != 13:
        return None

    action = frame[24:]
    if not action or action[0] != VENDOR_SPECIFIC_CATEGORY:
        return None
    if len(action) < 4 or action[1:4] != NINTENDO_OUI:
        return None

    vendor_data = action[4:]
    if not vendor_data or vendor_data[0] != LDN_PROTOCOL_ID:
        return None
    if len(vendor_data) < 8:
        raise ValueError("Nintendo LDN action has a truncated header")
    if vendor_data[2:4] != ADVERTISEMENT_PACKET_TYPE:
        return None

    return _parse_payload(vendor_data[8:], frame)
