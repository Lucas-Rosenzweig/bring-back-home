from typing import ClassVar, override

from IEEE80211.body.action.IEEE80211VendorAction import IEEE80211VendorAction
from IEEE80211.body.action.nintendo.NintendoLdnAdvertisement import NintendoLdnAdvertisement
from IEEE80211.body.action.nintendo.NintendoLdnPacketType import NintendoLdnPacketType
from IEEE80211.body.action.nintendo.NintendoLdnPayload import NintendoLdnPayload
from IEEE80211.body.action.nintendo.UnknownNintendoLdnPayload import UnknownNintendoLdnPayload
from IEEE80211.parsing.ByteReader import ByteReader


class NintendoLdnAction(IEEE80211VendorAction):
    LDN_PROTOCOL_ID: ClassVar[int] = 0x04

    protocol_id: int
    padding: bytes
    packet_type: int
    reserved: bytes
    payload: NintendoLdnPayload

    @override
    def parse(self) -> None:
        reader = ByteReader(self.raw)
        self.protocol_id = reader.read_u8("Nintendo protocol identifier")
        if self.protocol_id != self.LDN_PROTOCOL_ID:
            raise ValueError(
                f"Unsupported Nintendo protocol identifier 0x{self.protocol_id:02X}"
            )

        self.padding = reader.read_bytes(1, "Nintendo LDN padding")
        self.packet_type = reader.read_u16_be("Nintendo LDN packet type")
        self.reserved = reader.read_bytes(4, "Nintendo LDN reserved bytes")
        payload_raw = reader.read_remaining()

        match self.packet_type:
            case NintendoLdnPacketType.ADVERTISEMENT:
                self.payload = NintendoLdnAdvertisement(payload_raw)
            case _:
                self.payload = UnknownNintendoLdnPayload(payload_raw)

    def _packet_type_name(self) -> str:
        try:
            return NintendoLdnPacketType(self.packet_type).name
        except ValueError:
            return f"UNKNOWN (0x{self.packet_type:04X})"

    @override
    def print(self, indent: str = "") -> None:
        field_indent = f"{indent}  "
        print(f"{indent}Nintendo LDN Action:")
        print(f"{field_indent}Protocol ID         : 0x{self.protocol_id:02X}")
        print(f"{field_indent}Padding             : {self.padding.hex(' ')}")
        print(f"{field_indent}Packet Type         : {self._packet_type_name()}")
        print(f"{field_indent}Reserved            : {self.reserved.hex(' ')}")
        self.payload.print(field_indent)
