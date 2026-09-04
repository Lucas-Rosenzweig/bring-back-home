"""Selection of a game plugin from immutable LDN session metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pokemon_trade.api import TradeClient
from pokemon_trade.errors import AmbiguousGameError, UnsupportedGameError
from pokemon_trade.transport.base import SessionContext


@dataclass(frozen=True, slots=True)
class GameDescriptor:
    game_id: str
    label: str
    communication_ids: frozenset[int]
    create_client: Callable[[], TradeClient]

    def supports(self, session: SessionContext) -> bool:
        return session.communication_id in self.communication_ids


class GameRegistry:
    def __init__(self, descriptors: tuple[GameDescriptor, ...] = ()) -> None:
        self._descriptors: dict[str, GameDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: GameDescriptor) -> None:
        if not descriptor.game_id or not descriptor.game_id.isidentifier():
            raise ValueError("game_id must be a non-empty Python-style identifier")
        if descriptor.game_id in self._descriptors:
            raise ValueError(f"game plugin already registered: {descriptor.game_id}")
        if not descriptor.communication_ids:
            raise ValueError("a game descriptor needs at least one verified signature")
        self._descriptors[descriptor.game_id] = descriptor

    def resolve(
        self, session: SessionContext, game_id: str | None = None
    ) -> GameDescriptor:
        if game_id is not None and game_id != "auto":
            try:
                return self._descriptors[game_id]
            except KeyError as error:
                raise UnsupportedGameError(f"unknown game override: {game_id}") from error
        matches = [
            descriptor
            for descriptor in self._descriptors.values()
            if descriptor.supports(session)
        ]
        if not matches:
            raise UnsupportedGameError(
                f"unsupported LDN communication ID: 0x{session.communication_id:016X}"
            )
        if len(matches) > 1:
            raise AmbiguousGameError(
                "multiple game plugins match this LDN session: "
                + ", ".join(descriptor.game_id for descriptor in matches)
            )
        return matches[0]
