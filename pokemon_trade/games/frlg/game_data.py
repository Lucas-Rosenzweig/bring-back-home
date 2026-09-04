"""Local FRLG identity buffers used during RFU room entry."""

from __future__ import annotations

from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant, encode_gen3_text
from pokemon_trade.games.frlg.pokemon import FrlgTeam

RFU_GAME_DATA_SIZE = 26
TRAINER_CARD_SIZE = 100
RFU_CAN_LINK_NATIONALLY = 1 << 7
RFU_HAS_NATIONAL_DEX = 1 << 8
RFU_GAME_CLEAR = 1 << 9


def build_rfu_game_data(identity: FrlgIdentity) -> bytes:
    """Build the 26-byte NI game-data record for a started local trade room."""
    version = 4 if identity.variant is FrlgVariant.FIRERED else 5
    # `RfuGameCompatibilityData` puts language in bits 0–3, then the
    # capability flags in bits 7–9 and the game version in bits 10–13.  A
    # follower that advertises no national-link capability is rejected by a
    # real FRLG leader before UNI begins, even though its RFU transport works.
    compatibility = (
        (identity.language & 0x0F)
        | RFU_CAN_LINK_NATIONALLY
        | RFU_HAS_NATIONAL_DEX
        | RFU_GAME_CLEAR
        | (version << 10)
    )
    game_data = bytearray(13)
    game_data[0:2] = compatibility.to_bytes(2, "little")
    game_data[2:4] = identity.trainer_id.to_bytes(2, "little")
    game_data[10] = 0x84  # trade activity plus started-activity bit
    game_name = bytes(game_data).ljust(15, b"\0")
    user_name = encode_gen3_text(identity.name, 9, pad=0)
    result = (2).to_bytes(2, "little") + game_name + user_name
    assert len(result) == RFU_GAME_DATA_SIZE
    return result


def build_trainer_card(identity: FrlgIdentity, team: FrlgTeam) -> bytes:
    """Build the 100-byte card buffer pulled before FRLG opens the trade menu."""
    version = 4 if identity.variant is FrlgVariant.FIRERED else 5
    card = bytearray(TRAINER_CARD_SIZE)
    card[0] = 0  # gender is cosmetic; follower uses the neutral value.
    card[0x0E:0x10] = identity.trainer_id.to_bytes(2, "little")
    card[0x30:0x38] = encode_gen3_text(identity.name, 8, pad=0)
    card[0x38] = version
    for index, member in enumerate(team.members):
        species = int.from_bytes(member.canonical_blocks()["G"][:2], "little")
        offset = 0x54 + index * 2
        card[offset : offset + 2] = species.to_bytes(2, "little")
    return bytes(card)
