from __future__ import annotations

import unittest

from pokemon_trade.errors import AmbiguousGameError, UnsupportedGameError
from pokemon_trade.registry import GameDescriptor, GameRegistry
from pokemon_trade.transport.base import ParticipantAddress, SessionContext


def session(communication_id: int = 42) -> SessionContext:
    participant = ParticipantAddress("169.254.1.1", "02:00:00:00:00:01")
    return SessionContext(
        bytes(16),
        communication_id,
        7,
        1,
        "ldnclient",
        participant,
        participant,
        "169.254.1.255",
    )


class GameRegistryTest(unittest.TestCase):
    def test_resolves_a_single_verified_signature(self) -> None:
        descriptor = GameDescriptor("example", "Example", frozenset({42}), lambda: None)  # type: ignore[arg-type]

        self.assertIs(GameRegistry((descriptor,)).resolve(session()), descriptor)

    def test_rejects_unknown_and_ambiguous_sessions(self) -> None:
        first = GameDescriptor("one", "One", frozenset({42}), lambda: None)  # type: ignore[arg-type]
        second = GameDescriptor("two", "Two", frozenset({42}), lambda: None)  # type: ignore[arg-type]
        registry = GameRegistry((first, second))

        with self.assertRaises(AmbiguousGameError):
            registry.resolve(session())
        with self.assertRaises(UnsupportedGameError):
            registry.resolve(session(10))
        self.assertIs(registry.resolve(session(10), "one"), first)
