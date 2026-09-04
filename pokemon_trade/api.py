"""Game-agnostic request, progress and result types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol

from pokemon_trade.artifacts import PokemonArtifact
from pokemon_trade.errors import InvalidArtifactError

if TYPE_CHECKING:
    from pokemon_trade.transport.base import DatagramTransport


class TradeEventKind(StrEnum):
    LDN_READY = "ldn_ready"
    PEER_CONNECTED = "peer_connected"
    ROOM_ENTERED = "room_entered"
    MENU_READY = "menu_ready"
    OFFERED = "offered"
    COMMITTED = "committed"
    SAVING = "saving"
    LEAVING = "leaving"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """A structured, non-sensitive progress notification."""

    kind: TradeEventKind
    round_index: int | None = None
    details: Mapping[str, str | int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.round_index is not None and self.round_index < 1:
            raise ValueError("round_index is one-based")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class TradeStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class TradeRequest:
    """An immutable request shared by all game plugins.

    ``offered_slots`` defaults to the first requested party slots.  Plugins
    validate their own artifact format and game-specific options.
    """

    team: tuple[PokemonArtifact, ...]
    trade_count: int | None = None
    offered_slots: tuple[int, ...] = ()
    player_identity: Mapping[str, str | int] = field(default_factory=dict)
    variant: str | None = None
    options: Mapping[str, str | int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.team, tuple):
            raise TypeError("team must be an immutable tuple")
        if not 1 <= len(self.team) <= 6:
            raise InvalidArtifactError("a trade request requires one to six Pokémon")
        if self.trade_count is None:
            trade_count = len(self.team)
        else:
            trade_count = self.trade_count
        if not 1 <= trade_count <= 6:
            raise ValueError("trade_count must be between one and six")
        if trade_count > len(self.team):
            raise ValueError("trade_count cannot exceed the supplied team")
        offered_slots = self.offered_slots or tuple(range(trade_count))
        if len(offered_slots) != trade_count:
            raise ValueError("offered_slots must contain one slot per trade")
        if len(set(offered_slots)) != len(offered_slots) or any(
            not 0 <= slot < len(self.team) for slot in offered_slots
        ):
            raise ValueError("offered_slots must be distinct team indexes")
        if self.variant is not None and not self.variant:
            raise ValueError("variant must be non-empty when supplied")
        object.__setattr__(self, "trade_count", trade_count)
        object.__setattr__(self, "offered_slots", tuple(offered_slots))
        object.__setattr__(self, "player_identity", MappingProxyType(dict(self.player_identity)))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class TradeResult:
    status: TradeStatus
    received: tuple[PokemonArtifact, ...]
    updated_team: tuple[PokemonArtifact, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        if len(self.updated_team) > 6:
            raise ValueError("updated_team cannot contain more than six Pokémon")
        if self.status is TradeStatus.COMPLETED and self.error is not None:
            raise ValueError("a completed trade cannot carry an error")
        if self.status is TradeStatus.COMPLETED and not self.received:
            raise ValueError("a completed trade must contain committed artifacts")


EventSink = Callable[[TradeEvent], Awaitable[None] | None]


class TradeClient(Protocol):
    """Implemented by a single game plugin, never by the CLI."""

    async def validate(self, request: TradeRequest) -> None: ...

    async def run(
        self,
        transport: DatagramTransport,
        request: TradeRequest,
        emit: EventSink,
    ) -> TradeResult: ...
