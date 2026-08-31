"""Minimal, project-owned implementation of the Nintendo LDN wire format."""

from __future__ import annotations

import hashlib
import hmac
import socket
import struct
from dataclasses import dataclass, field
from pathlib import Path

from Crypto.Cipher import AES

ACCEPT_ALL = 0
ACCEPT_NONE = 1

ADVERTISE_PLAIN = 1
ADVERTISE_AES_CTR = 2
ADVERTISE_AES_GCM = 3

AUTH_PLAIN = 0
AUTH_AES_GCM = 1

SECURITY_PROD = 1
PLATFORM_NX = 0

CHALLENGE_KEY = bytes.fromhex(
    "f84b487fb37251c263bf11609036589266af70ca79b44c93c7370c5769c0f602"
)


class BufferReader:
    def __init__(self, data: bytes, endian: str = ">") -> None:
        self.data = data
        self.endian = endian
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise ValueError("truncated LDN structure")
        value = self.data[self.offset : end]
        self.offset = end
        return value

    def skip(self, size: int) -> None:
        self.take(size)

    def integer(self, size: int) -> int:
        return int.from_bytes(
            self.take(size), "big" if self.endian == ">" else "little"
        )


@dataclass(frozen=True, slots=True)
class MACAddress:
    value: bytes = bytes(6)

    def __post_init__(self) -> None:
        if len(self.value) != 6:
            raise ValueError("a MAC address must contain 6 bytes")

    @classmethod
    def parse(cls, value: str | bytes | MACAddress) -> MACAddress:
        if isinstance(value, MACAddress):
            return value
        if isinstance(value, bytes):
            return cls(value)
        if not isinstance(value, str):
            raise TypeError("MAC address must be text or bytes")
        fields = value.split(":")
        if len(fields) != 6:
            raise ValueError(f"invalid MAC address: {value}")
        return cls(bytes(int(field, 16) for field in fields))

    def __bytes__(self) -> bytes:
        return self.value

    def __str__(self) -> str:
        return ":".join(f"{byte:02X}" for byte in self.value)


@dataclass(slots=True)
class NetworkId:
    local_communication_id: int = 0
    scene_id: int = 0
    ssid: bytes = bytes(16)

    def encode(self, endian: str) -> bytes:
        order = "big" if endian == ">" else "little"
        if len(self.ssid) != 16:
            raise ValueError("LDN SSID must contain 16 bytes")
        return (
            self.local_communication_id.to_bytes(8, order)
            + bytes(2)
            + self.scene_id.to_bytes(2, order)
            + bytes(4)
            + self.ssid
        )

    @classmethod
    def decode(cls, data: bytes, endian: str) -> NetworkId:
        reader = BufferReader(data, endian)
        communication_id = reader.integer(8)
        reader.skip(2)
        scene_id = reader.integer(2)
        reader.skip(4)
        return cls(communication_id, scene_id, reader.take(16))


@dataclass(slots=True)
class ParticipantInfo:
    ip_address: str = "0.0.0.0"
    mac_address: MACAddress = field(default_factory=MACAddress)
    connected: bool = False
    name: bytes = b""
    app_version: int = 0
    platform: int = PLATFORM_NX


@dataclass(slots=True)
class NetworkInfo:
    protocol: int
    address: MACAddress = field(default_factory=MACAddress)
    band: int = 0
    channel: int = 0
    local_communication_id: int = 0
    scene_id: int = 0
    ssid: bytes = bytes(16)
    version: int = 0
    server_random: bytes = bytes(16)
    security_mode: int = SECURITY_PROD
    app_version: int = 0
    accept_policy: int = ACCEPT_ALL
    max_participants: int = 0
    num_participants: int = 0
    participants: list[ParticipantInfo] = field(default_factory=list)
    application_data: bytes = b""
    challenge: int = 0
    nonce: bytes = b""

    def same_network(self, other: NetworkInfo) -> bool:
        return (
            self.address == other.address
            and self.channel == other.channel
            and self.local_communication_id == other.local_communication_id
            and self.scene_id == other.scene_id
            and self.ssid == other.ssid
            and self.version == other.version
            and self.server_random == other.server_random
            and self.security_mode == other.security_mode
        )


def load_keys(path: Path) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"invalid prod.keys line: {line!r}")
        keys[name.strip()] = bytes.fromhex(value.strip())
    return keys


class KeyDerivation:
    def __init__(self, keys: dict[str, bytes], protocol: int) -> None:
        if protocol not in (1, 3):
            raise ValueError(f"unsupported LDN protocol: {protocol}")
        self.keys = keys
        self.protocol = protocol

    @staticmethod
    def _aes_decrypt(value: bytes, key: bytes) -> bytes:
        return AES.new(key, AES.MODE_ECB).decrypt(value)

    def _derive(self, data: bytes, source: bytes) -> bytes:
        master_name = "master_key_00" if self.protocol == 1 else "master_key_12"
        key = self.keys[master_name]
        key = self._aes_decrypt(self.keys["aes_kek_generation_source"], key)
        key = self._aes_decrypt(source, key)
        key = self._aes_decrypt(self.keys["aes_key_generation_source"], key)
        return self._aes_decrypt(hashlib.sha256(data).digest()[:16], key)

    def advertisement_key(self, network_id: bytes) -> bytes:
        source = bytes.fromhex("191884743e24c77d87c69e4207d0c438")
        return self._derive(network_id, source)

    def authentication_key(self, client_random: bytes) -> bytes:
        source = bytes.fromhex("f1e7018419a84f711da714c2cf919c9c")
        return self._derive(client_random, source)

    def data_key(self, server_random: bytes, passphrase: bytes) -> bytes:
        source = bytes.fromhex("f1e7018419a84f711da714c2cf919c9c")
        return self._derive(server_random + passphrase, source)


@dataclass(frozen=True, slots=True)
class _DecodedAdvertisement:
    server_random: bytes
    security_mode: int
    accept_policy: int
    app_version: int
    band: int
    channel: int
    max_participants: int
    num_participants: int
    application_data: bytes
    challenge: int


def _decode_v1(payload: bytes) -> tuple[_DecodedAdvertisement, list[ParticipantInfo]]:
    reader = BufferReader(payload)
    server_random = reader.take(16)
    security_mode = reader.integer(2)
    accept_policy = reader.integer(1)
    reader.skip(1)
    band_channel = reader.integer(2)
    band = band_channel >> 10
    channel = band_channel & 0x3FF
    max_participants = reader.integer(1)
    num_participants = reader.integer(1)
    participants: list[ParticipantInfo] = []
    for _ in range(8):
        participant = ParticipantInfo(
            ip_address=socket.inet_ntoa(reader.take(4)),
            mac_address=MACAddress(reader.take(6)),
            connected=bool(reader.integer(1)),
            platform=reader.integer(1),
            name=reader.take(32).rstrip(b"\0"),
            app_version=reader.integer(2),
        )
        reader.skip(10)
        participants.append(participant)
    app_version = participants[0].app_version
    reader.skip(2)
    application_size = reader.integer(2)
    application_data = reader.take(384)[:application_size]
    reader.skip(412)
    challenge = reader.integer(8)
    return (
        _DecodedAdvertisement(
            server_random,
            security_mode,
            accept_policy,
            app_version,
            band,
            channel,
            max_participants,
            num_participants,
            application_data,
            challenge,
        ),
        participants,
    )


def _decode_v2(payload: bytes) -> tuple[_DecodedAdvertisement, list[ParticipantInfo]]:
    reader = BufferReader(payload)
    server_random = reader.take(16)
    challenge = reader.integer(8)
    security_mode = reader.integer(1)
    accept_policy = reader.integer(1)
    app_version = reader.integer(2)
    reader.skip(8)
    band_channel = reader.integer(2)
    band = band_channel >> 10
    channel = band_channel & 0x3FF
    max_participants = reader.integer(1)
    participant_count = reader.integer(1)
    participants = [ParticipantInfo() for _ in range(8)]
    for _ in range(participant_count):
        ip_address = socket.inet_ntoa(reader.take(4))
        mac_address = MACAddress(reader.take(6))
        index = reader.integer(1)
        platform = reader.integer(1)
        name = reader.take(32).rstrip(b"\0")
        reader.skip(4)
        if index < len(participants):
            participants[index] = ParticipantInfo(
                ip_address=ip_address,
                mac_address=mac_address,
                connected=True,
                name=name,
                app_version=app_version,
                platform=platform,
            )
    application_data = reader.take(reader.integer(2))
    if reader.remaining:
        raise ValueError("unexpected bytes after LDN advertisement payload")
    return (
        _DecodedAdvertisement(
            server_random,
            security_mode,
            accept_policy,
            app_version,
            band,
            channel,
            max_participants,
            participant_count,
            application_data,
            challenge,
        ),
        participants,
    )


def decode_advertisement(
    action: bytes,
    source: MACAddress,
    channel: int,
    keys: dict[str, bytes],
    protocols: tuple[int, ...] = (1, 3),
) -> NetworkInfo:
    failures: list[tuple[int, Exception]] = []
    for protocol in protocols:
        try:
            return _decode_advertisement(action, source, channel, keys, protocol)
        except Exception as error:  # noqa: BLE001 - probe both protocol generations
            failures.append((protocol, error))
    error = ValueError("unable to decrypt the LDN advertisement")
    for protocol, failure in failures:
        error.add_note(f"protocol {protocol}: {failure!r}")
    raise error


def _decode_advertisement(
    action: bytes,
    source: MACAddress,
    channel: int,
    keys: dict[str, bytes],
    protocol: int,
) -> NetworkInfo:
    reader = BufferReader(action)
    if reader.take(4) != b"\x7f\x00\x22\xaa":
        raise ValueError("not a Nintendo vendor action")
    if reader.integer(1) != 4:
        raise ValueError("not an LDN action")
    reader.skip(1)
    if reader.integer(2) != 0x101:
        raise ValueError("not an LDN advertisement")
    reader.skip(4)

    header = action[reader.offset : reader.offset + 0x28]
    network_id_bytes = reader.take(32)
    network_id = NetworkId.decode(network_id_bytes, ">")
    version = reader.integer(1)
    if version not in (2, 3, 4):
        raise ValueError(f"unsupported advertisement version: {version}")
    encryption = reader.integer(1)
    expected = ADVERTISE_AES_CTR if protocol == 1 else ADVERTISE_AES_GCM
    if encryption not in (ADVERTISE_PLAIN, expected):
        raise ValueError("advertisement encryption does not match protocol")
    size = reader.integer(2)
    nonce = reader.take(4)
    derivation = KeyDerivation(keys, protocol)
    key = derivation.advertisement_key(network_id_bytes)

    if encryption == ADVERTISE_PLAIN:
        if size != 0x500:
            raise ValueError("unexpected plaintext advertisement size")
        plaintext = reader.take(32 + size)
    elif encryption == ADVERTISE_AES_CTR:
        if size != 0x500:
            raise ValueError("unexpected AES-CTR advertisement size")
        plaintext = AES.new(key, AES.MODE_CTR, nonce=nonce).decrypt(
            reader.take(32 + size)
        )
    else:
        tag = reader.take(16)
        ciphertext = reader.take(size)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce + bytes(8))
        cipher.update(header)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    if reader.remaining:
        raise ValueError("unexpected bytes after LDN advertisement")

    if encryption in (ADVERTISE_PLAIN, ADVERTISE_AES_CTR):
        digest, plaintext = plaintext[:32], plaintext[32:]
        expected_digest = hashlib.sha256(header + bytes(32) + plaintext).digest()
        if not hmac.compare_digest(digest, expected_digest):
            raise ValueError("invalid advertisement SHA-256")

    info, participants = (
        _decode_v2(plaintext)
        if encryption == ADVERTISE_AES_GCM
        else _decode_v1(plaintext)
    )
    return NetworkInfo(
        protocol=protocol,
        address=source,
        band=info.band,
        channel=channel,
        local_communication_id=network_id.local_communication_id,
        scene_id=network_id.scene_id,
        ssid=network_id.ssid,
        version=version,
        server_random=info.server_random,
        security_mode=info.security_mode,
        app_version=info.app_version,
        accept_policy=info.accept_policy,
        max_participants=info.max_participants,
        num_participants=info.num_participants,
        participants=participants,
        application_data=info.application_data,
        challenge=info.challenge,
        nonce=nonce,
    )


def encode_advertisement_gcm(network: NetworkInfo, keys: dict[str, bytes]) -> bytes:
    """Encode protocol 3 advertisements for deterministic protocol tests."""
    network_id = NetworkId(
        network.local_communication_id,
        network.scene_id,
        network.ssid,
    )
    payload = bytearray(network.server_random)
    payload += network.challenge.to_bytes(8, "big")
    payload += bytes([network.security_mode, network.accept_policy])
    payload += network.app_version.to_bytes(2, "big")
    payload += bytes(8)
    payload += ((network.band << 10) | network.channel).to_bytes(2, "big")
    payload += bytes([network.max_participants, network.num_participants])
    for index, participant in enumerate(network.participants):
        if not participant.connected:
            continue
        payload += socket.inet_aton(participant.ip_address)
        payload += bytes(participant.mac_address)
        payload += bytes([index, participant.platform])
        payload += participant.name.ljust(32, b"\0")
        payload += bytes(4)
    payload += len(network.application_data).to_bytes(2, "big")
    payload += network.application_data

    preamble = b"\x7f\x00\x22\xaa\x04\x00\x01\x01" + bytes(4)
    header = (
        network_id.encode(">")
        + bytes([network.version, ADVERTISE_AES_GCM])
        + len(payload).to_bytes(2, "big")
        + network.nonce
    )
    key = KeyDerivation(keys, 3).advertisement_key(network_id.encode(">"))
    cipher = AES.new(key, AES.MODE_GCM, nonce=network.nonce + bytes(8))
    cipher.update(header)
    ciphertext, tag = cipher.encrypt_and_digest(bytes(payload))
    return preamble + header + tag + ciphertext


def encode_challenge(token: int, nonce: int, device_id: int) -> bytes:
    body = bytearray(bytes(8))
    body += struct.pack("<QQQ", token, nonce, device_id)
    body += bytes(16 + 0x60 + 8 * 8 + 8 * 64)
    if len(body) != 0x2D0:
        raise AssertionError("invalid challenge layout")
    return bytes(4) + hmac.digest(CHALLENGE_KEY, body, "sha256") + bytes(12) + body


def encode_authentication_request(
    network: NetworkInfo,
    keys: dict[str, bytes],
    client_random: bytes,
    nickname: bytes,
    app_version: int,
    challenge_nonce: int,
    device_id: int,
) -> bytes:
    if len(nickname) > 32 or len(client_random) != 16:
        raise ValueError("invalid authentication identity")
    payload = bytearray(nickname.ljust(32, b"\0"))
    payload += app_version.to_bytes(2, "big")
    payload += bytes([PLATFORM_NX]) + bytes(29)
    if network.version >= 3:
        payload += bytes(0x24)
        payload += encode_challenge(network.challenge, challenge_nonce, device_id)

    network_id = NetworkId(
        network.local_communication_id,
        network.scene_id,
        network.ssid,
    )
    auth_format = AUTH_PLAIN if network.protocol == 1 else AUTH_AES_GCM
    size = len(payload)
    header = (
        bytes(
            [
                network.version,
                size & 0xFF,
                0,
                0,
                size >> 8,
                auth_format,
                0,
                0,
            ]
        )
        + network_id.encode("<")
        + network.server_random
        + client_random
    )
    output = bytearray(b"\x00\x22\xaa\x01\x02\x00" + header)
    if auth_format == AUTH_AES_GCM:
        key = KeyDerivation(keys, network.protocol).authentication_key(client_random)
        cipher = AES.new(key, AES.MODE_GCM, nonce=header[:12])
        cipher.update(header)
        ciphertext, tag = cipher.encrypt_and_digest(bytes(payload))
        output += tag + ciphertext
    else:
        output += payload
    return bytes(output)


def validate_authentication_response(
    data: bytes,
    network: NetworkInfo,
    keys: dict[str, bytes],
    client_random: bytes,
) -> None:
    reader = BufferReader(data)
    if reader.take(6) != b"\x00\x22\xaa\x01\x02\x00":
        raise ValueError("not an LDN authentication frame")
    header = data[6 : 6 + 0x48]
    version = reader.integer(1)
    size_low = reader.integer(1)
    status = reader.integer(1)
    is_response = reader.integer(1)
    size_high = reader.integer(1)
    auth_format = reader.integer(1)
    reader.skip(2)
    network_id = NetworkId.decode(reader.take(32), "<")
    server_random = reader.take(16)
    returned_client_random = reader.take(16)
    expected_format = AUTH_PLAIN if network.protocol == 1 else AUTH_AES_GCM
    if version != network.version or auth_format != expected_format or not is_response:
        raise ValueError("unexpected LDN authentication response")
    if network_id != NetworkId(
        network.local_communication_id,
        network.scene_id,
        network.ssid,
    ):
        raise ValueError("authentication response targets another network")
    if (
        server_random != network.server_random
        or returned_client_random != client_random
    ):
        raise ValueError("authentication response random mismatch")
    size = (size_high << 8) | size_low
    if auth_format == AUTH_AES_GCM:
        tag = reader.take(16)
        ciphertext = reader.take(size)
        cipher = AES.new(
            KeyDerivation(keys, network.protocol).authentication_key(client_random),
            AES.MODE_GCM,
            nonce=header[:12],
        )
        cipher.update(header)
        cipher.decrypt_and_verify(ciphertext, tag)
    else:
        reader.take(size)
    if reader.remaining:
        raise ValueError("unexpected authentication response bytes")
    if status:
        raise PermissionError(f"LDN authentication rejected with status {status}")
