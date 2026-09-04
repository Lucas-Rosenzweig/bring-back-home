from __future__ import annotations

import unittest

import trio

from pokemon_trade.api import TradeEvent, TradeEventKind, TradeRequest, TradeStatus
from pokemon_trade.errors import TradeTimeoutError
from pokemon_trade.games.frlg.client import FrlgTradeClient
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.games.frlg.trade.engine import FrlgProtocolTuning
from pokemon_trade.games.frlg.trade.model import (
    FrlgCommand,
    FrlgWireSignal,
    FrlgWireSignalKind,
)
from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext


def pokemon(value: int) -> Pk3:
    header = bytearray(32)
    header[:4] = value.to_bytes(4, "little")
    header[4:8] = (4).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes([value]) * 48)


class FakeTransport:
    session = SessionContext(
        bytes(16),
        0x01006FA0233F8000,
        1,
        1,
        "fake0",
        ParticipantAddress("169.254.1.2", "02:00:00:00:00:02"),
        ParticipantAddress("169.254.1.1", "02:00:00:00:00:01"),
        "169.254.1.255",
    )

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        return None

    async def receive(self) -> Datagram:
        raise AssertionError("fake FRLG driver owns semantic input")

    async def aclose(self) -> None:
        return None


class FakeDriver:
    def __init__(self, received: Pk3) -> None:
        self.signals = iter(
            (
                FrlgWireSignal(FrlgWireSignalKind.PEER_CONNECTED),
                FrlgWireSignal(FrlgWireSignalKind.ROOM_ENTERED),
                FrlgWireSignal(FrlgWireSignalKind.MENU_READY),
                FrlgWireSignal(FrlgWireSignalKind.TRADE_COMMITTED, received.party_bytes),
                FrlgWireSignal(FrlgWireSignalKind.SAVE_COMPLETE),
                FrlgWireSignal(FrlgWireSignalKind.EXITED),
            )
        )
        self.commands: list[FrlgCommand] = []
        self.closed = False

    async def start(self) -> None:
        return None

    async def send(self, command: FrlgCommand) -> None:
        self.commands.append(command)

    async def receive(self) -> FrlgWireSignal:
        return next(self.signals)

    async def aclose(self) -> None:
        self.closed = True


class SilentDriver:
    def __init__(self) -> None:
        self.closed = False

    async def start(self) -> None:
        return None

    async def send(self, command: FrlgCommand) -> None:
        return None

    async def receive(self) -> FrlgWireSignal:
        await trio.sleep_forever()
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        self.closed = True


class FrlgTradeClientTest(unittest.TestCase):
    def test_game_client_uses_the_same_eventful_path_as_a_driver(self) -> None:
        async def scenario() -> None:
            received = pokemon(2)
            driver = FakeDriver(received)
            client = FrlgTradeClient(lambda _, __: driver)
            events: list[TradeEvent] = []
            result = await client.run(
                FakeTransport(),
                TradeRequest((pokemon(1).to_artifact(),)),
                events.append,
            )
            self.assertEqual(result.status, TradeStatus.COMPLETED)
            self.assertEqual(result.received[0].data, received.decrypted_pk3_bytes())
            self.assertEqual([event.kind for event in events], [
                TradeEventKind.PEER_CONNECTED,
                TradeEventKind.ROOM_ENTERED,
                TradeEventKind.MENU_READY,
                TradeEventKind.OFFERED,
                TradeEventKind.COMMITTED,
                TradeEventKind.SAVING,
                TradeEventKind.LEAVING,
                TradeEventKind.COMPLETED,
            ])
            self.assertTrue(driver.closed)

        trio.run(scenario)

    def test_silent_driver_raises_a_typed_timeout_and_closes(self) -> None:
        async def scenario() -> None:
            driver = SilentDriver()
            client = FrlgTradeClient(
                lambda _, __: driver,
                tuning=FrlgProtocolTuning(phase_timeout_seconds=0.01),
            )
            events: list[TradeEvent] = []
            with self.assertRaises(TradeTimeoutError):
                await client.run(
                    FakeTransport(),
                    TradeRequest((pokemon(1).to_artifact(),)),
                    events.append,
                )
            self.assertEqual([event.kind for event in events], [TradeEventKind.FAILED])
            self.assertTrue(driver.closed)

        trio.run(scenario)
