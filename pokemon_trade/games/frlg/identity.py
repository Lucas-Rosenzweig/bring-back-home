"""Non-sensitive typed FRLG identity values used by the game plugin."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pokemon_trade.errors import InvalidArtifactError


class FrlgVariant(StrEnum):
    FIRERED = "firered"
    LEAFGREEN = "leafgreen"


@dataclass(frozen=True, slots=True)
class FrlgIdentity:
    """Validated local identity; values are never included in default logs."""

    trainer_id: int
    secret_id: int
    name: str
    variant: FrlgVariant
    language: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.trainer_id <= 0xFFFF:
            raise ValueError("trainer_id must fit in 16 bits")
        if not 0 <= self.secret_id <= 0xFFFF:
            raise ValueError("secret_id must fit in 16 bits")
        if not 1 <= len(self.name) <= 7:
            raise ValueError("FRLG trainer name must contain one to seven characters")
        if not 0 <= self.language <= 0xFF:
            raise ValueError("language must fit in one byte")


_GEN3_TEXT = {
    0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·",
    0xB0: "…", 0xB8: ",", 0xBA: "/",
}
_GEN3_TEXT.update({0xA1 + index: str(index) for index in range(10)})
_GEN3_TEXT.update({0xBB + index: chr(ord("A") + index) for index in range(26)})
_GEN3_TEXT.update({0xD5 + index: chr(ord("a") + index) for index in range(26)})
_GEN3_ENCODE = {value: key for key, value in _GEN3_TEXT.items()}


def encode_gen3_text(value: str, width: int, *, pad: int = 0xFF) -> bytes:
    """Encode a bounded international Gen III text field with an EOS marker."""
    if width < 1:
        raise ValueError("Gen III text field width must be positive")
    try:
        encoded = bytes(_GEN3_ENCODE[character] for character in value)
    except KeyError as error:
        raise InvalidArtifactError(f"unsupported Gen III text character: {error.args[0]!r}") from error
    return (encoded[: width - 1] + b"\xFF").ljust(width, bytes((pad,)))


def decode_gen3_text(value: bytes) -> str:
    result: list[str] = []
    for byte in value:
        if byte == 0xFF:
            break
        result.append(_GEN3_TEXT.get(byte, "?"))
    return "".join(result)


@dataclass(frozen=True, slots=True)
class LinkPlayerRecord:
    """The 28-byte FRLG `LinkPlayer` record transported in a 60-byte block."""

    identity: FrlgIdentity
    progress_flags: int = 0
    gender: int = 0
    link_type: int = 0
    player_id: int = 0

    def encode(self) -> bytes:
        version = 0x4004 if self.identity.variant is FrlgVariant.FIRERED else 0x4005
        trainer_id = self.identity.trainer_id | (self.identity.secret_id << 16)
        return b"".join(
            (
                version.to_bytes(2, "little"),
                (0x8000).to_bytes(2, "little"),
                trainer_id.to_bytes(4, "little"),
                encode_gen3_text(self.identity.name, 8, pad=0),
                bytes((self.progress_flags & 0xFF, 0, self.progress_flags & 0xFF, self.gender & 0xFF)),
                self.link_type.to_bytes(4, "little"),
                self.player_id.to_bytes(2, "little"),
                self.identity.language.to_bytes(2, "little"),
            )
        )

    def block(self) -> bytes:
        magic = b"GameFreak inc.\0\0"
        return magic + self.encode() + magic
