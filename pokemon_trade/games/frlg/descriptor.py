"""Only observed FRLG LDN signatures belong in automatic selection."""

from collections.abc import Callable

from pokemon_trade.api import TradeRequest
from pokemon_trade.games.frlg.client import FrlgTradeClient, FrlgWireDriver
from pokemon_trade.games.frlg.trade.engine import FrlgProtocolTuning
from pokemon_trade.registry import GameDescriptor
from pokemon_trade.transport.base import DatagramTransport

FRLG_OBSERVED_COMMUNICATION_IDS = frozenset({0x01006FA0233F8000})


def frlg_descriptor(
    driver_factory: Callable[[DatagramTransport, TradeRequest], FrlgWireDriver],
    *,
    tuning: FrlgProtocolTuning = FrlgProtocolTuning(),
) -> GameDescriptor:
    """Build a registry descriptor without assuming a live radio adapter."""
    return GameDescriptor(
        "frlg",
        "Pokémon FireRed / LeafGreen",
        FRLG_OBSERVED_COMMUNICATION_IDS,
        lambda: FrlgTradeClient(driver_factory, tuning=tuning),
    )
