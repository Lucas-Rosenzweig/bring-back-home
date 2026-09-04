"""Strict, self-contained handling of Generation III `.pk3` party data.

The encrypted payload is the 48-byte Gen III boxed Pokémon structure.  A
party `.pk3` appends 20 runtime bytes, so a boxed 80-byte input can be
normalized deterministically without guessing any live battle state.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.artifacts import PokemonArtifact
from pokemon_trade.errors import InvalidArtifactError

BOX_SIZE = 80
PARTY_SIZE = 100
HEADER_SIZE = 32
ENCRYPTED_SIZE = 48
PARTY_TAIL_SIZE = PARTY_SIZE - BOX_SIZE
CHECKSUM_OFFSET = 28

# The personality value selects the physical ordering of four 12-byte blocks:
# Growth, Attacks, EVs/condition, and Miscellaneous.
SUBSTRUCTURE_ORDERS = (
    "GAEM",
    "GAME",
    "GEAM",
    "GEMA",
    "GMAE",
    "GMEA",
    "AGME",
    "AGEM",
    "AEGM",
    "AEMG",
    "AMGE",
    "AMEG",
    "EGAM",
    "EGMA",
    "EAGM",
    "EAMG",
    "EMGA",
    "EMAG",
    "MGAE",
    "MGEA",
    "MAGE",
    "MAEG",
    "MEGA",
    "MEAG",
)
CANONICAL_BLOCK_ORDER = "GAEM"


def _xor_crypt(payload: bytes, key: int) -> bytes:
    if len(payload) != ENCRYPTED_SIZE:
        raise ValueError("Gen III encrypted data must be exactly 48 bytes")
    return b"".join(
        (int.from_bytes(payload[offset : offset + 4], "little") ^ key).to_bytes(
            4, "little"
        )
        for offset in range(0, ENCRYPTED_SIZE, 4)
    )


def secure_checksum(decrypted_secure_data: bytes) -> int:
    """Return the Gen III checksum over 24 little-endian words."""
    if len(decrypted_secure_data) != ENCRYPTED_SIZE:
        raise ValueError("Gen III secure data must be exactly 48 bytes")
    return sum(
        int.from_bytes(decrypted_secure_data[offset : offset + 2], "little")
        for offset in range(0, ENCRYPTED_SIZE, 2)
    ) & 0xFFFF


@dataclass(frozen=True, slots=True)
class Pk3:
    """A validated 100-byte Gen III party Pokémon, preserved byte-for-byte."""

    party_bytes: bytes

    def __post_init__(self) -> None:
        if len(self.party_bytes) != PARTY_SIZE:
            raise InvalidArtifactError("a normalized .pk3 must contain 100 bytes")
        object.__setattr__(self, "party_bytes", bytes(self.party_bytes))
        self.validate()

    @classmethod
    def parse(cls, data: bytes) -> Pk3:
        """Accept a raw wire `.ek3` or normal PKHeX-style decrypted `.pk3`.

        The internal representation is always the encrypted, personality-
        shuffled party form used by FRLG's RFU blocks.  Public artifacts are
        converted back to the ordinary decrypted `.pk3` representation.
        """
        if len(data) == BOX_SIZE:
            data = data + bytes(PARTY_TAIL_SIZE)
        if len(data) != PARTY_SIZE:
            raise InvalidArtifactError(".pk3 input must contain either 80 or 100 bytes")
        try:
            return cls(data)
        except InvalidArtifactError as encrypted_error:
            header = bytes(data[:HEADER_SIZE])
            canonical_secure_data = bytes(data[HEADER_SIZE:BOX_SIZE])
            if secure_checksum(canonical_secure_data) != int.from_bytes(
                header[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2], "little"
            ):
                raise encrypted_error
            return cls.from_decrypted(header, canonical_secure_data, data[BOX_SIZE:])

    @classmethod
    def from_decrypted(
        cls,
        header: bytes,
        decrypted_secure_data: bytes,
        party_tail: bytes = bytes(PARTY_TAIL_SIZE),
    ) -> Pk3:
        """Build a valid test or synthetic entry from plaintext secure data."""
        if len(header) != HEADER_SIZE or len(party_tail) != PARTY_TAIL_SIZE:
            raise ValueError("invalid Gen III header or party-tail length")
        if len(decrypted_secure_data) != ENCRYPTED_SIZE:
            raise ValueError("invalid Gen III secure-data length")
        normalized_header = bytearray(header)
        normalized_header[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = secure_checksum(
            decrypted_secure_data
        ).to_bytes(2, "little")
        personality = int.from_bytes(normalized_header[0:4], "little")
        trainer_id = int.from_bytes(normalized_header[4:8], "little")
        order = SUBSTRUCTURE_ORDERS[personality % len(SUBSTRUCTURE_ORDERS)]
        physical = b"".join(
            decrypted_secure_data[
                CANONICAL_BLOCK_ORDER.index(block) * 12 : (CANONICAL_BLOCK_ORDER.index(block) + 1) * 12
            ]
            for block in order
        )
        encrypted = _xor_crypt(physical, personality ^ trainer_id)
        return cls(bytes(normalized_header) + encrypted + party_tail)

    @property
    def personality(self) -> int:
        return int.from_bytes(self.party_bytes[0:4], "little")

    @property
    def trainer_id(self) -> int:
        return int.from_bytes(self.party_bytes[4:8], "little")

    @property
    def checksum(self) -> int:
        return int.from_bytes(
            self.party_bytes[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2], "little"
        )

    @property
    def block_order(self) -> str:
        return SUBSTRUCTURE_ORDERS[self.personality % len(SUBSTRUCTURE_ORDERS)]

    def decrypted_secure_data(self) -> bytes:
        return _xor_crypt(
            self.party_bytes[HEADER_SIZE:BOX_SIZE], self.personality ^ self.trainer_id
        )

    def canonical_blocks(self) -> dict[str, bytes]:
        """Return G/A/E/M blocks independent of their personality ordering."""
        decrypted = self.decrypted_secure_data()
        return {
            block: decrypted[index * 12 : (index + 1) * 12]
            for index, block in enumerate(self.block_order)
        }

    def decrypted_pk3_bytes(self) -> bytes:
        """Return a conventional decrypted `.pk3` party entry for callers/export."""
        canonical = b"".join(self.canonical_blocks()[block] for block in CANONICAL_BLOCK_ORDER)
        return self.party_bytes[:HEADER_SIZE] + canonical + self.party_bytes[BOX_SIZE:]

    def validate(self) -> None:
        actual = secure_checksum(self.decrypted_secure_data())
        if actual != self.checksum:
            raise InvalidArtifactError(
                f"invalid .pk3 checksum: expected 0x{self.checksum:04X}, got 0x{actual:04X}"
            )

    def to_artifact(self) -> PokemonArtifact:
        return PokemonArtifact("pk3", self.decrypted_pk3_bytes(), 3)


@dataclass(frozen=True, slots=True)
class FrlgTeam:
    """A local party and its explicit offered slots for a single request."""

    members: tuple[Pk3, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.members) <= 6:
            raise InvalidArtifactError("a FRLG party must contain one to six .pk3 entries")

    @classmethod
    def from_artifacts(cls, artifacts: tuple[PokemonArtifact, ...]) -> FrlgTeam:
        if any(artifact.format != "pk3" or artifact.generation != 3 for artifact in artifacts):
            raise InvalidArtifactError("FRLG accepts only Generation III .pk3 artifacts")
        return cls(tuple(Pk3.parse(artifact.data) for artifact in artifacts))

    def replace(self, slot: int, received: Pk3) -> FrlgTeam:
        if not 0 <= slot < len(self.members):
            raise InvalidArtifactError("offered FRLG slot is outside the local party")
        updated = list(self.members)
        updated[slot] = received
        return FrlgTeam(tuple(updated))

    def artifacts(self) -> tuple[PokemonArtifact, ...]:
        return tuple(member.to_artifact() for member in self.members)
