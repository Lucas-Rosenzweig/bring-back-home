from __future__ import annotations

import unittest

from pokemon_trade.api import TradeEvent, TradeEventKind, TradeRequest, TradeResult, TradeStatus
from pokemon_trade.artifacts import PokemonArtifact
from pokemon_trade.errors import InvalidArtifactError


def artifact(value: int = 1) -> PokemonArtifact:
    return PokemonArtifact("pk3", bytes([value]) * 100, 3)


class TradeApiTest(unittest.TestCase):
    def test_request_defaults_to_one_trade_per_team_member_and_first_slots(self) -> None:
        request = TradeRequest((artifact(1), artifact(2)))

        self.assertEqual(request.trade_count, 2)
        self.assertEqual(request.offered_slots, (0, 1))

    def test_request_rejects_invalid_trade_shape(self) -> None:
        with self.assertRaises(InvalidArtifactError):
            TradeRequest(())
        with self.assertRaises(ValueError):
            TradeRequest((artifact(),), trade_count=2)
        with self.assertRaises(ValueError):
            TradeRequest((artifact(), artifact(2)), offered_slots=(0, 0))

    def test_progress_details_are_immutable(self) -> None:
        event = TradeEvent(TradeEventKind.COMMITTED, 1, {"attempt": 1})

        with self.assertRaises(TypeError):
            event.details["attempt"] = 2  # type: ignore[index]

    def test_completed_result_requires_a_commit(self) -> None:
        with self.assertRaises(ValueError):
            TradeResult(TradeStatus.COMPLETED, (), (artifact(),))
