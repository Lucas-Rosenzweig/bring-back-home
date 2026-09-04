from __future__ import annotations

import unittest

from pokemon_trade.errors import InvalidArtifactError
from pokemon_trade.games.frlg.pokemon import (
    BOX_SIZE,
    PARTY_SIZE,
    FrlgTeam,
    Pk3,
)


def synthetic_pk3(personality: int = 1) -> Pk3:
    header = bytearray(32)
    header[0:4] = personality.to_bytes(4, "little")
    header[4:8] = (0xAABBCCDD).to_bytes(4, "little")
    plaintext = bytes(range(48))
    return Pk3.from_decrypted(bytes(header), plaintext)


class Pk3Test(unittest.TestCase):
    def test_encrypts_decrypts_and_preserves_a_party_entry(self) -> None:
        pokemon = synthetic_pk3(23)

        self.assertEqual(len(pokemon.party_bytes), PARTY_SIZE)
        self.assertEqual(set(pokemon.canonical_blocks()), {"G", "A", "E", "M"})
        self.assertEqual(
            b"".join(pokemon.canonical_blocks()[block] for block in "GAEM"),
            bytes(range(48)),
        )
        self.assertEqual(Pk3.parse(pokemon.party_bytes).party_bytes, pokemon.party_bytes)

    def test_normalizes_a_box_entry_with_a_zero_runtime_tail(self) -> None:
        pokemon = synthetic_pk3()

        normalized = Pk3.parse(pokemon.party_bytes[:BOX_SIZE])

        self.assertEqual(len(normalized.party_bytes), PARTY_SIZE)
        self.assertEqual(normalized.party_bytes[:BOX_SIZE], pokemon.party_bytes[:BOX_SIZE])
        self.assertEqual(normalized.party_bytes[BOX_SIZE:], bytes(20))

    def test_accepts_decrypted_pk3_and_exports_that_standard_form(self) -> None:
        wire = synthetic_pk3(7)

        parsed = Pk3.parse(wire.decrypted_pk3_bytes())

        self.assertEqual(parsed.party_bytes, wire.party_bytes)
        self.assertEqual(parsed.to_artifact().data, wire.decrypted_pk3_bytes())

    def test_rejects_wrong_size_and_corrupt_checksum(self) -> None:
        with self.assertRaises(InvalidArtifactError):
            Pk3.parse(bytes(81))
        corrupt = bytearray(synthetic_pk3().party_bytes)
        corrupt[32] ^= 1
        with self.assertRaises(InvalidArtifactError):
            Pk3.parse(bytes(corrupt))

    def test_replaces_only_an_explicit_party_slot(self) -> None:
        first = synthetic_pk3(1)
        second = synthetic_pk3(2)
        received = synthetic_pk3(3)

        updated = FrlgTeam((first, second)).replace(1, received)

        self.assertEqual(updated.members, (first, received))
