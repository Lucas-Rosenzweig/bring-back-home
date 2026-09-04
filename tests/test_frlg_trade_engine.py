from __future__ import annotations

import unittest

from pokemon_trade.api import TradeEventKind, TradeRequest, TradeStatus
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.games.frlg.trade.engine import FrlgTradeEngine
from pokemon_trade.games.frlg.trade.model import (
    FrlgCommandKind,
    FrlgWireSignal,
    FrlgWireSignalKind,
)


def pokemon(value: int) -> Pk3:
    header = bytearray(32)
    header[:4] = value.to_bytes(4, "little")
    header[4:8] = (3).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes([value]) * 48)


def signal(kind: FrlgWireSignalKind, received: Pk3 | None = None) -> FrlgWireSignal:
    return FrlgWireSignal(kind, received.party_bytes if received else None)


class FrlgTradeEngineTest(unittest.TestCase):
    def test_commits_only_after_valid_commit_and_leaves_after_last_round(self) -> None:
        offered = pokemon(1)
        received = pokemon(2)
        engine = FrlgTradeEngine(TradeRequest((offered.to_artifact(),)))
        engine.start(0)
        engine.receive(signal(FrlgWireSignalKind.PEER_CONNECTED), 1)
        engine.receive(signal(FrlgWireSignalKind.ROOM_ENTERED), 2)
        commands, events = engine.receive(signal(FrlgWireSignalKind.MENU_READY), 3)

        self.assertEqual(commands[0].kind, FrlgCommandKind.OFFER_SLOT)
        self.assertEqual(events[-1].kind, TradeEventKind.OFFERED)
        commands, events = engine.receive(signal(FrlgWireSignalKind.TRADE_COMMITTED, received), 4)
        self.assertEqual(commands[0].kind, FrlgCommandKind.SAVE)
        self.assertEqual(events[0].kind, TradeEventKind.COMMITTED)
        commands, _ = engine.receive(signal(FrlgWireSignalKind.SAVE_COMPLETE), 5)
        self.assertEqual(commands[0].kind, FrlgCommandKind.LEAVE)
        engine.receive(signal(FrlgWireSignalKind.EXITED), 6)

        result = engine.result
        assert result is not None
        self.assertEqual(result.status, TradeStatus.COMPLETED)
        self.assertEqual(result.received[0].data, received.decrypted_pk3_bytes())

    def test_cancel_before_commit_never_exposes_an_artifact(self) -> None:
        engine = FrlgTradeEngine(TradeRequest((pokemon(1).to_artifact(),)))
        engine.start(0)
        commands, _ = engine.cancel()
        self.assertEqual(commands[0].kind, FrlgCommandKind.LEAVE)
        engine.receive(signal(FrlgWireSignalKind.EXITED), 1)

        result = engine.result
        assert result is not None
        self.assertEqual(result.status, TradeStatus.CANCELLED)
        self.assertEqual(result.received, ())

    def test_cancel_after_a_commit_reports_the_durable_round_as_partial(self) -> None:
        first = pokemon(1)
        second = pokemon(2)
        received = pokemon(3)
        engine = FrlgTradeEngine(
            TradeRequest((first.to_artifact(), second.to_artifact()), trade_count=2)
        )
        engine.start(0)
        engine.receive(signal(FrlgWireSignalKind.PEER_CONNECTED), 1)
        engine.receive(signal(FrlgWireSignalKind.ROOM_ENTERED), 2)
        engine.receive(signal(FrlgWireSignalKind.MENU_READY), 3)
        engine.receive(signal(FrlgWireSignalKind.TRADE_COMMITTED, received), 4)

        engine.receive(signal(FrlgWireSignalKind.CANCELLED), 5)

        result = engine.result
        assert result is not None
        self.assertEqual(result.status, TradeStatus.PARTIAL)
        self.assertEqual(result.received[0].data, received.decrypted_pk3_bytes())
