"""Documented PIA LDN v6 key and nonce primitives for FRLG."""

from __future__ import annotations

import ipaddress
import zlib

from Crypto.Cipher import AES

from pokemon_trade.errors import CryptoError
from pokemon_trade.games.frlg.pia.packet import PiaPacketV16, compress_packet_payload, decompress_packet_payload


def derive_ldn_session_key(ssid: bytes, game_key: bytes) -> bytes:
    if len(ssid) != 16 or len(game_key) not in {16, 24, 32}:
        raise ValueError("PIA LDN key derivation requires 16-byte SSID and AES key")
    return AES.new(game_key, AES.MODE_ECB).encrypt(ssid)


def ldn_nonce(network_id: int, source_ip: str, packet_nonce: bytes) -> bytes:
    """Build the documented 12-byte PIA LDN AES-GCM nonce for v6.16–6.42."""
    if not 0 <= network_id <= 0xFFFFFFFF or len(packet_nonce) != 8:
        raise ValueError("invalid PIA LDN network ID or packet nonce")
    try:
        address = ipaddress.IPv4Address(source_ip).packed
    except ipaddress.AddressValueError as error:
        raise ValueError("PIA LDN source must be an IPv4 address") from error
    prefix = bytes(
        left ^ right for left, right in zip(network_id.to_bytes(4, "little"), address)
    )
    return prefix + packet_nonce


def frlg_ldn_nonce(ssid: bytes, source_ip: str, packet_nonce: bytes) -> bytes:
    """FRLG v16 nonce: CRC32(SSID[1:]) XOR IPv4 (big endian), plus wire nonce."""
    if len(ssid) != 16:
        raise ValueError("FRLG PIA requires a 16-byte LDN SSID")
    network_id = zlib.crc32(ssid[1:]) & 0xFFFFFFFF
    try:
        address = int(ipaddress.IPv4Address(source_ip))
    except ipaddress.AddressValueError as error:
        raise ValueError("FRLG PIA source must be IPv4") from error
    return ((network_id ^ address) & 0xFFFFFFFF).to_bytes(4, "big") + packet_nonce


def decrypt_frlg_v16(packet: PiaPacketV16, ssid: bytes, game_key: bytes, source_ip: str) -> tuple[bytes, bytes]:
    """Decrypt a v16 packet and return application bytes plus its plaintext footer."""
    if not packet.encrypted:
        raise CryptoError("FRLG PIA packets must be encrypted")
    key = derive_ldn_session_key(ssid, game_key)
    plaintext = decrypt_gcm(key, frlg_ldn_nonce(ssid, source_ip, packet.nonce), packet.payload, packet.authentication_tag, b"")
    padding = packet.flags >> 4
    if padding > len(plaintext) or plaintext[len(plaintext) - padding :] != bytes((0xFF,)) * padding if padding else False:
        raise CryptoError("invalid FRLG PIA packet padding")
    body = plaintext[:-padding] if padding else plaintext
    if packet.footer_size > len(body):
        raise CryptoError("FRLG PIA footer exceeds plaintext")
    application = body[: len(body) - packet.footer_size] if packet.footer_size else body
    footer = body[len(body) - packet.footer_size :] if packet.footer_size else b""
    if packet.flags & 1:
        application = decompress_packet_payload(application)
    return application, footer


def encrypt_frlg_v16(
    *,
    ssid: bytes,
    game_key: bytes,
    source_ip: str,
    destination_variable_id: int,
    source_variable_id: int,
    packet_id: int,
    nonce: bytes,
    application: bytes,
    footer: bytes = b"",
    compressed: bool = False,
    establishing: bool = False,
) -> PiaPacketV16:
    if len(footer) > 0xFF:
        raise ValueError("PIA v16 footer exceeds one-byte size")
    body = compress_packet_payload(application) if compressed else bytes(application)
    body += footer
    padding = (-len(body)) % 16
    plaintext = body + bytes((0xFF,)) * padding
    flags = (padding << 4) | (1 if compressed else 0) | (2 if establishing else 0)
    key = derive_ldn_session_key(ssid, game_key)
    ciphertext, tag = encrypt_gcm(key, frlg_ldn_nonce(ssid, source_ip, nonce), plaintext, b"")
    return PiaPacketV16(
        True,
        flags,
        destination_variable_id,
        source_variable_id,
        packet_id,
        nonce,
        tag,
        ciphertext,
        len(footer),
    )


def encrypt_gcm(key: bytes, nonce: bytes, plaintext: bytes, associated_data: bytes) -> tuple[bytes, bytes]:
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=8)
    cipher.update(associated_data)
    encrypted, tag = cipher.encrypt_and_digest(plaintext)
    return encrypted, tag


def decrypt_gcm(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, associated_data: bytes) -> bytes:
    try:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=8)
        cipher.update(associated_data)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as error:
        raise CryptoError("PIA AES-GCM authentication failed") from error
