from typing import ClassVar, override

from IEEE80211.body.action.IEEE80211VendorAction import IEEE80211VendorAction
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisement import NintendoLdnAdvertisement
from IEEE80211.body.action.nintendo.NintendoLdnPacketType import NintendoLdnPacketType
from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload
from IEEE80211.body.action.nintendo.UnknownNintendoLdnPayload import UnknownNintendoLdnPayload


class NintendoLdnAction(IEEE80211VendorAction):
    LDN_PROTOCOL_ID: ClassVar[bytes] = b"\x04"

    protocol_id: bytes
    padding: bytes
    packet_type: bytes
    reserved: bytes
    payload: NintendoLdnPayload

    @override
    def parse(self) -> None:
        if len(self.raw) < 8:
            raise ValueError("Nintendo LDN action must contain an 8-byte header")

        self.protocol_id = self.raw[0:1]
        if self.protocol_id != self.LDN_PROTOCOL_ID:
            raise ValueError(
                f"Unsupported Nintendo protocol identifier 0x{self.protocol_id.hex().upper()}"
            )

        self.padding = self.raw[1:2]
        self.packet_type = self.raw[2:4]
        self.reserved = self.raw[4:8]
        payload_raw = self.raw[8:]

        if self.packet_type == NintendoLdnPacketType.ADVERTISEMENT.value:
            self.payload = NintendoLdnAdvertisement(payload_raw)
        else:
            self.payload = UnknownNintendoLdnPayload(payload_raw)

    def _packet_type_name(self) -> str:
        try:
            return NintendoLdnPacketType(self.packet_type).name
        except ValueError:
            return f"UNKNOWN (0x{self.packet_type.hex().upper()})"

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Nintendo LDN Action:")
        print(f"{field_indent}Protocol ID         : 0x{self.protocol_id.hex().upper()}")
        print(f"{field_indent}Padding             : {self.padding.hex(' ')}")
        print(f"{field_indent}Packet Type         : {self._packet_type_name()}")
        print(f"{field_indent}Reserved            : {self.reserved.hex(' ')}")
        self.payload.print(field_indent)
