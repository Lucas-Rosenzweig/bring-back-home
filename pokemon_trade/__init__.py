"""Typed public API for local Pokémon trade clients.

The package deliberately contains no LDN radio implementation.  A game plugin
receives an established datagram transport and owns every game-specific wire
protocol above it.
"""

from pokemon_trade.api import (
    TradeEvent,
    TradeEventKind,
    TradeRequest,
    TradeResult,
    TradeStatus,
)
from pokemon_trade.artifacts import PokemonArtifact, export_artifacts
from pokemon_trade.errors import TradeError
from pokemon_trade.registry import GameRegistry

__all__ = [
    "GameRegistry",
    "PokemonArtifact",
    "TradeError",
    "TradeEvent",
    "TradeEventKind",
    "TradeRequest",
    "TradeResult",
    "TradeStatus",
    "export_artifacts",
]
