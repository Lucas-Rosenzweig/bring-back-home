from typing import override

from IEEE80211.body.action.nintendo.NintendoLdnAdvertisementFormat import (
    NintendoLdnAdvertisementFormat,
)
from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload
from IEEE80211.body.action.nintendo.NintendoLdnSessionInfo import NintendoLdnSessionInfo


class NintendoLdnAdvertisement(NintendoLdnPayload):
    session_info: NintendoLdnSessionInfo
    ldn_version: bytes
    encryption_type: bytes
    data_size: bytes
    nonce: bytes
    gcm_tag: bytes | None
    integrity_hash: bytes | None
    encrypted_advertisement_data: bytes
    trailing_data: bytes

    @override
    def parse(self) -> None:
        header_size = NintendoLdnSessionInfo.SIZE + 1 + 1 + 2 + 4
        if len(self.raw) < header_size:
            raise ValueError("Nintendo LDN advertisement must contain a 40-byte header")

        self.session_info = NintendoLdnSessionInfo(self.raw[0:32])
        self.ldn_version = self.raw[32:33]
        self.encryption_type = self.raw[33:34]
        self.data_size = self.raw[34:36]
        self.nonce = self.raw[36:40]
        self.gcm_tag = None
        self.integrity_hash = None

        payload_size = int.from_bytes(self.data_size, "big")
        if self.encryption_type == NintendoLdnAdvertisementFormat.AES_GCM.value:
            if len(self.raw) < 56:
                raise ValueError("Truncated GCM authentication tag")
            if len(self.raw) < 56 + payload_size:
                raise ValueError("Truncated GCM ciphertext")
            self.gcm_tag = self.raw[40:56]
            self.encrypted_advertisement_data = self.raw[56:56 + payload_size]
            self.trailing_data = self.raw[56 + payload_size:]
        elif self.encryption_type == NintendoLdnAdvertisementFormat.PLAIN.value:
            if len(self.raw) < 72:
                raise ValueError("Truncated advertisement hash")
            if len(self.raw) < 72 + payload_size:
                raise ValueError("Truncated plain advertisement data")
            self.integrity_hash = self.raw[40:72]
            self.encrypted_advertisement_data = self.raw[72:72 + payload_size]
            self.trailing_data = self.raw[72 + payload_size:]
        elif self.encryption_type == NintendoLdnAdvertisementFormat.AES_CTR.value:
            encrypted_size = 32 + payload_size
            if len(self.raw) < 40 + encrypted_size:
                raise ValueError("Truncated AES-CTR advertisement data")
            self.encrypted_advertisement_data = self.raw[40:40 + encrypted_size]
            self.trailing_data = self.raw[40 + encrypted_size:]
        else:
            self.encrypted_advertisement_data = self.raw[40:]
            self.trailing_data = b""

    @property
    def is_encrypted(self) -> bool:
        return self.encryption_type in {
            NintendoLdnAdvertisementFormat.AES_CTR.value,
            NintendoLdnAdvertisementFormat.AES_GCM.value,
        }

    def _format_name(self) -> str:
        try:
            return NintendoLdnAdvertisementFormat(self.encryption_type).name
        except ValueError:
            return f"UNKNOWN (0x{self.encryption_type.hex().upper()})"

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Advertisement Payload:")
        self.session_info.print(field_indent)
        print(f"{field_indent}LDN Version         : 0x{self.ldn_version.hex().upper()}")
        print(f"{field_indent}Encryption Type     : {self._format_name()}")
        print(
            f"{field_indent}Data Size           : "
            + f"{int.from_bytes(self.data_size, 'big')} bytes ({self.data_size.hex(' ').upper()})"
        )
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
