from typing import override

from IEEE80211.body.action.nintendo.NintendoLdnAdvertisementFormat import (
    NintendoLdnAdvertisementFormat,
)
from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload
from IEEE80211.body.action.nintendo.NintendoLdnSessionInfo import NintendoLdnSessionInfo
from IEEE80211.parsing.ByteReader import ByteReader


class NintendoLdnAdvertisement(NintendoLdnPayload):
    session_info: NintendoLdnSessionInfo
    ldn_version: int
    encryption_type: int
    data_size: int
    nonce: bytes
    gcm_tag: bytes | None
    integrity_hash: bytes | None
    encrypted_advertisement_data: bytes
    trailing_data: bytes

    @override
    def parse(self) -> None:
        reader = ByteReader(self.raw)
        self.session_info = NintendoLdnSessionInfo(
            reader.read_bytes(NintendoLdnSessionInfo.SIZE, "LDN session info")
        )
        self.ldn_version = reader.read_u8("LDN version")
        self.encryption_type = reader.read_u8("advertisement format")
        self.data_size = reader.read_u16_be("advertisement data size")
        self.nonce = reader.read_bytes(4, "advertisement nonce")
        self.gcm_tag = None
        self.integrity_hash = None

        match self.encryption_type:
            case NintendoLdnAdvertisementFormat.AES_GCM:
                self.gcm_tag = reader.read_bytes(16, "GCM authentication tag")
                self.encrypted_advertisement_data = reader.read_bytes(
                    self.data_size, "GCM ciphertext"
                )
            case NintendoLdnAdvertisementFormat.PLAIN:
                self.integrity_hash = reader.read_bytes(32, "advertisement hash")
                self.encrypted_advertisement_data = reader.read_bytes(
                    self.data_size, "plain advertisement data"
                )
            case NintendoLdnAdvertisementFormat.AES_CTR:
                self.encrypted_advertisement_data = reader.read_bytes(
                    32 + self.data_size, "AES-CTR advertisement data"
                )
            case _:
                self.encrypted_advertisement_data = reader.read_remaining()

        self.trailing_data = reader.read_remaining()

    @property
    def is_encrypted(self) -> bool:
        return self.encryption_type in {
            NintendoLdnAdvertisementFormat.AES_CTR,
            NintendoLdnAdvertisementFormat.AES_GCM,
        }

    def _format_name(self) -> str:
        try:
            return NintendoLdnAdvertisementFormat(self.encryption_type).name
        except ValueError:
            return f"UNKNOWN (0x{self.encryption_type:02X})"

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Advertisement Payload:")
        self.session_info.print(field_indent)
        print(f"{field_indent}LDN Version         : {self.ldn_version}")
        print(f"{field_indent}Encryption Type     : {self._format_name()}")
        print(f"{field_indent}Data Size           : {self.data_size}")
        print(f"{field_indent}Nonce               : {self.nonce.hex(' ')}")
        if self.gcm_tag is not None:
            print(f"{field_indent}GCM Tag             : {self.gcm_tag.hex(' ')}")
        if self.integrity_hash is not None:
            print(f"{field_indent}Integrity Hash      : {self.integrity_hash.hex(' ')}")
        print(
            f"{field_indent}Encrypted Data      : "
            + self.encrypted_advertisement_data.hex(" ")
        )
        if self.trailing_data:
            print(f"{field_indent}Trailing Data       : {self.trailing_data.hex(' ')}")
