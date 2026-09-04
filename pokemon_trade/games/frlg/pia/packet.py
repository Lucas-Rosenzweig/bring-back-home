"""Strict PIA packet codecs; FRLG uses the v16 envelope, with v11 retained for compatibility tests."""

from __future__ import annotations

from dataclasses import dataclass

import zstandard

from pokemon_trade.errors import MalformedDatagramError

PIA_MAGIC = bytes.fromhex("32AB9864")
PIA_HEADER_VERSION = 11
PIA_V11_HEADER_SIZE = 28
PIA_PACKET_COMPRESSED = 0x01
PIA_V16_HEADER_SIZE = 29


@dataclass(frozen=True, slots=True)
class PiaMessage:
    flags: int
    protocol_type: int
    port: int
    destination: int
    payload: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.flags <= 0xFF or not 0 <= self.protocol_type <= 0xFF:
            raise ValueError("PIA message flags and protocol type must fit in one byte")
        if not 0 <= self.port <= 0xFFFFFF:
            raise ValueError("PIA message port must fit in 24 bits")
        if not 0 <= self.destination <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("PIA message destination must fit in 64 bits")
        if len(self.payload) > 0xFFFF:
            raise ValueError("PIA message payload exceeds 16-bit length")
        object.__setattr__(self, "payload", bytes(self.payload))


@dataclass(frozen=True, slots=True)
class PiaPacketV11:
    encrypted: bool
    destination_variable_id: int
    source_variable_id: int
    packet_id: int
    nonce: bytes
    authentication_tag: bytes
    payload: bytes
    footer: bytes = b""

    def __post_init__(self) -> None:
        for value, name in (
            (self.destination_variable_id, "destination_variable_id"),
            (self.source_variable_id, "source_variable_id"),
            (self.packet_id, "packet_id"),
        ):
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"{name} must fit in 16 bits")
        if len(self.nonce) != 8:
            raise ValueError("PIA v11 packet nonce must contain eight bytes")
        if len(self.authentication_tag) != 8:
            raise ValueError("PIA v11 packet tag must contain eight bytes")
        if len(self.footer) > 0xFF:
            raise ValueError("PIA footer exceeds one-byte size")
        object.__setattr__(self, "nonce", bytes(self.nonce))
        object.__setattr__(self, "authentication_tag", bytes(self.authentication_tag))
        object.__setattr__(self, "payload", bytes(self.payload))
        object.__setattr__(self, "footer", bytes(self.footer))

    def header_bytes(self) -> bytes:
        return b"".join(
            (
                PIA_MAGIC,
                bytes([(0x80 if self.encrypted else 0) | PIA_HEADER_VERSION]),
                self.destination_variable_id.to_bytes(2, "big"),
                self.source_variable_id.to_bytes(2, "big"),
                self.packet_id.to_bytes(2, "big"),
                bytes([len(self.footer)]),
                self.nonce,
                self.authentication_tag,
            )
        )

    def encode(self) -> bytes:
        return self.header_bytes() + self.payload + self.footer

    @classmethod
    def parse(cls, packet: bytes) -> PiaPacketV11:
        if len(packet) < PIA_V11_HEADER_SIZE:
            raise MalformedDatagramError("truncated PIA v11 header")
        if packet[:4] != PIA_MAGIC:
            raise MalformedDatagramError("invalid PIA magic")
        version_flags = packet[4]
        if version_flags & 0x7F != PIA_HEADER_VERSION:
            raise MalformedDatagramError(
                f"unsupported PIA header version: {version_flags & 0x7F}"
            )
        footer_size = packet[11]
        if len(packet) < PIA_V11_HEADER_SIZE + footer_size:
            raise MalformedDatagramError("PIA footer exceeds packet length")
        footer_start = len(packet) - footer_size
        return cls(
            encrypted=bool(version_flags & 0x80),
            destination_variable_id=int.from_bytes(packet[5:7], "big"),
            source_variable_id=int.from_bytes(packet[7:9], "big"),
            packet_id=int.from_bytes(packet[9:11], "big"),
            nonce=packet[12:20],
            authentication_tag=packet[20:28],
            payload=packet[28:footer_start],
            footer=packet[footer_start:],
        )


@dataclass(frozen=True, slots=True)
class PiaPacketV16:
    """PIA 6.32–7.2 envelope used by the observed FRLG transport."""

    encrypted: bool
    flags: int
    destination_variable_id: int
    source_variable_id: int
    packet_id: int
    nonce: bytes
    authentication_tag: bytes
    payload: bytes
    footer_size: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.flags <= 0xFF or not 0 <= self.footer_size <= 0xFF:
            raise ValueError("invalid PIA v16 flags or footer size")
        for value in (self.destination_variable_id, self.source_variable_id, self.packet_id):
            if not 0 <= value <= 0xFFFF:
                raise ValueError("PIA v16 IDs must fit in uint16")
        if len(self.nonce) != 8 or len(self.authentication_tag) != 8:
            raise ValueError("PIA v16 nonce and tag must each contain eight bytes")
        object.__setattr__(self, "nonce", bytes(self.nonce))
        object.__setattr__(self, "authentication_tag", bytes(self.authentication_tag))
        object.__setattr__(self, "payload", bytes(self.payload))

    def header_bytes(self) -> bytes:
        return b"".join(
            (
                PIA_MAGIC,
                bytes(((0x80 if self.encrypted else 0) | 16, self.flags)),
                self.destination_variable_id.to_bytes(2, "big"),
                self.source_variable_id.to_bytes(2, "big"),
                self.packet_id.to_bytes(2, "big"),
                bytes((self.footer_size,)),
                self.nonce,
                self.authentication_tag,
            )
        )

    def encode(self) -> bytes:
        return self.header_bytes() + self.payload

    @classmethod
    def parse(cls, packet: bytes) -> PiaPacketV16:
        if len(packet) < PIA_V16_HEADER_SIZE:
            raise MalformedDatagramError("truncated PIA v16 header")
        if packet[:4] != PIA_MAGIC or packet[4] & 0x7F != 16:
            raise MalformedDatagramError("not a PIA v16 packet")
        return cls(
            encrypted=bool(packet[4] & 0x80),
            flags=packet[5],
            destination_variable_id=int.from_bytes(packet[6:8], "big"),
            source_variable_id=int.from_bytes(packet[8:10], "big"),
            packet_id=int.from_bytes(packet[10:12], "big"),
            footer_size=packet[12],
            nonce=packet[13:21],
            authentication_tag=packet[21:29],
            payload=packet[29:],
        )

def encode_messages(messages: tuple[PiaMessage, ...]) -> bytes:
    """Encode explicit v11 message fields; field elision is decode-only."""
    result = bytearray()
    for message in messages:
        start = len(result)
        result.append(0x1F)  # every v11 field is present
        result.append(message.flags)
        result += len(message.payload).to_bytes(2, "big")
        result.append(message.protocol_type)
        result += message.port.to_bytes(3, "big")
        result += message.destination.to_bytes(8, "big")
        result += message.payload
        result += bytes((-((len(result) - start)) % 4))
    return bytes(result)


def decode_messages(data: bytes) -> tuple[PiaMessage, ...]:
    """Decode v11 messages, carrying forward fields omitted by the wire."""
    cursor = 0
    previous: PiaMessage | None = None
    messages: list[PiaMessage] = []
    while cursor < len(data):
        start = cursor
        fields = _take(data, cursor, 1, "field bitmap")[0]
        cursor += 1
        if fields & ~0x1F:
            raise MalformedDatagramError("unsupported PIA v11 message field bits")
        try:
            flags = (
                _take(data, cursor, 1, "message flags")[0]
                if fields & 0x01
                else _previous(previous, "flags")
            )
            cursor += 1 if fields & 0x01 else 0
            payload_size = (
                int.from_bytes(_take(data, cursor, 2, "payload size"), "big")
                if fields & 0x02
                else _previous_payload_size(previous)
            )
            cursor += 2 if fields & 0x02 else 0
            protocol_type = (
                _take(data, cursor, 1, "protocol type")[0]
                if fields & 0x04
                else _previous(previous, "protocol_type")
            )
            cursor += 1 if fields & 0x04 else 0
            port = (
                int.from_bytes(_take(data, cursor, 3, "protocol port"), "big")
                if fields & 0x04
                else _previous(previous, "port")
            )
            cursor += 3 if fields & 0x04 else 0
            destination = (
                int.from_bytes(_take(data, cursor, 8, "destination"), "big")
                if fields & 0x08
                else _previous(previous, "destination")
            )
            cursor += 8 if fields & 0x08 else 0
        except IndexError as error:
            raise MalformedDatagramError("truncated PIA v11 message fields") from error
        if cursor + payload_size > len(data):
            raise MalformedDatagramError("truncated PIA v11 message payload")
        message = PiaMessage(flags, protocol_type, port, destination, data[cursor : cursor + payload_size])
        cursor += payload_size
        padding = (-((cursor - start)) % 4)
        if data[cursor : cursor + padding] != bytes(padding):
            raise MalformedDatagramError("invalid non-zero PIA v11 message padding")
        cursor += padding
        previous = message
        messages.append(message)
    return tuple(messages)


def encode_messages_v16(messages: tuple[PiaMessage, ...]) -> bytes:
    """Encode self-contained PIA v16 messages (no inherited fields required)."""
    result = bytearray()
    for message in messages:
        fields = 0x06 | (0x01 if message.flags else 0)
        result.append(fields)
        if message.flags:
            result.append(message.flags)
        result += len(message.payload).to_bytes(2, "big")
        result += bytes((message.protocol_type,))
        result += message.payload
    return bytes(result)


def decode_messages_v16(data: bytes) -> tuple[PiaMessage, ...]:
    """Decode v16 tiling, stopping only at canonical 0xFF packet padding."""
    cursor = 0
    previous: PiaMessage | None = None
    messages: list[PiaMessage] = []
    while cursor < len(data):
        if data[cursor] == 0xFF:
            if data[cursor:] != bytes((0xFF,)) * (len(data) - cursor):
                raise MalformedDatagramError("non-canonical PIA v16 packet padding")
            break
        fields = _take(data, cursor, 1, "v16 field bitmap")[0]
        cursor += 1
        if fields & ~0x1F:
            raise MalformedDatagramError("unsupported PIA v16 message fields")
        # PIA v6.32+ hosts commonly omit zero message flags even on the first
        # tile.  Size and protocol still have to be explicit for that first
        # tile; all later omitted values inherit from the preceding tile.
        flags = (
            _take(data, cursor, 1, "v16 message flags")[0]
            if fields & 1
            else (previous.flags if previous is not None else 0)
        )
        cursor += 1 if fields & 1 else 0
        size = (
            int.from_bytes(_take(data, cursor, 2, "v16 payload size"), "big")
            if fields & 2
            else _previous_payload_size(previous)
        )
        cursor += 2 if fields & 2 else 0
        protocol = (
            _take(data, cursor, 1, "v16 protocol type")[0]
            if fields & 4
            else _previous(previous, "protocol_type")
        )
        cursor += 1 if fields & 4 else 0
        port = (
            _take(data, cursor, 1, "v16 protocol port")[0]
            if fields & 8
            else (previous.port if previous is not None else 0)
        )
        cursor += 1 if fields & 8 else 0
        # v6.32+ reserves one protocol-specific byte behind bit 0x10.  The
        # FRLG Reliable/Net/Session handlers do not assign it semantics, but
        # it must be consumed to keep subsequent tiles aligned.
        if fields & 0x10:
            _take(data, cursor, 1, "v16 protocol extension")
            cursor += 1
        if cursor + size > len(data):
            raise MalformedDatagramError("truncated PIA v16 message payload")
        message = PiaMessage(flags, protocol, port, 0, data[cursor : cursor + size])
        cursor += size
        previous = message
        messages.append(message)
    return tuple(messages)


def compress_packet_payload(payload: bytes) -> bytes:
    return zstandard.ZstdCompressor().compress(payload)


def decompress_packet_payload(payload: bytes, *, max_output_size: int = 1472) -> bytes:
    try:
        return zstandard.ZstdDecompressor().decompress(payload, max_output_size=max_output_size)
    except zstandard.ZstdError as error:
        raise MalformedDatagramError("invalid compressed PIA payload") from error


def _previous(message: PiaMessage | None, field: str) -> int:
    if message is None:
        raise MalformedDatagramError("first PIA message omits required fields")
    return int(getattr(message, field))


def _previous_payload_size(message: PiaMessage | None) -> int:
    if message is None:
        raise MalformedDatagramError("first PIA message omits its payload size")
    return len(message.payload)


def _take(data: bytes, offset: int, size: int, field: str) -> bytes:
    value = data[offset : offset + size]
    if len(value) != size:
        raise MalformedDatagramError(f"truncated PIA v11 {field}")
    return value
