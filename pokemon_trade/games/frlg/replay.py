"""Recover FRLG's ephemeral inputs from an expurgated deterministic trace."""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.errors import MalformedDatagramError
from pokemon_trade.games.frlg.gba.frame import ControlFrame, FrameType, parse_frame
from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import PiaPacketV16, decode_messages_v16
from pokemon_trade.games.frlg.pia.reliable import RELIABLE_APP_DATA, ReliableWireFrame
from pokemon_trade.games.frlg.pia.session import PiaProtocol
from pokemon_trade.transport.replay import ReplayTransport


@dataclass(frozen=True, slots=True)
class FrlgReplayEntropy:
    """Captured per-run values required for byte-exact output verification."""

    local_variable_id: int
    session_nonce: bytes
    rfu_connect_id: bytes
    packet_nonces: tuple[bytes, ...]


def extract_frlg_replay_entropy(
    transport: ReplayTransport,
    game_key: bytes,
) -> FrlgReplayEntropy:
    """Decode only local ephemeral values; no identity or Pokémon is exposed."""
    local_variable_id: int | None = None
    session_nonce: bytes | None = None
    rfu_connect_id: bytes | None = None
    packet_nonces: list[bytes] = []

    for record in transport.records:
        if record.direction != "out":
            continue
        packet = PiaPacketV16.parse(record.payload)
        packet_nonces.append(packet.nonce)
        if local_variable_id is None and packet.source_variable_id >= 2:
            local_variable_id = packet.source_variable_id
        application, _ = decrypt_frlg_v16(
            packet,
            transport.session.ssid,
            game_key,
            record.source[0],
        )
        for message in decode_messages_v16(application):
            if message.protocol_type == PiaProtocol.SESSION and message.payload[:1] == b"\0":
                protocol_count = message.payload[1] if len(message.payload) >= 2 else 0
                nonce_offset = 2 + protocol_count * 2 + 2
                candidate = message.payload[nonce_offset : nonce_offset + 4]
                if len(candidate) == 4:
                    session_nonce = candidate
            if message.protocol_type != PiaProtocol.RELIABLE:
                continue
            reliable = ReliableWireFrame.parse(message.payload)
            if not reliable.flags & RELIABLE_APP_DATA:
                continue
            try:
                frame = parse_frame(reliable.payload)
            except MalformedDatagramError:
                continue
            if (
                isinstance(frame, ControlFrame)
                and frame.frame_type is FrameType.CONNECT
                and len(frame.body) == 2
            ):
                rfu_connect_id = frame.body

    if local_variable_id is None or session_nonce is None or rfu_connect_id is None:
        raise MalformedDatagramError("FRLG replay lacks its ephemeral handshake values")
    return FrlgReplayEntropy(
        local_variable_id,
        session_nonce,
        rfu_connect_id,
        tuple(packet_nonces),
    )
