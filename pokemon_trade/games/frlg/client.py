"""FRLG `TradeClient` composition over a game-specific wire driver."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import trio

from pokemon_trade.api import EventSink, TradeEvent, TradeEventKind, TradeRequest, TradeResult
from pokemon_trade.errors import ProtocolStateError, TradeTimeoutError
from pokemon_trade.games.frlg.pokemon import FrlgTeam
from pokemon_trade.games.frlg.trade.engine import FrlgProtocolTuning, FrlgTradeEngine
from pokemon_trade.games.frlg.trade.model import FrlgCommand, FrlgWireSignal
from pokemon_trade.service import emit_event
from pokemon_trade.transport.base import DatagramTransport


class FrlgWireDriver(Protocol):
    """Adapter from the PIA/RFU stack to semantic FRLG transaction signals."""

    async def start(self) -> None: ...

    async def send(self, command: FrlgCommand) -> None: ...

    async def receive(self) -> FrlgWireSignal: ...

    async def aclose(self) -> None: ...


class FrlgTradeClient:
    """Run the game-independent API through an FRLG wire implementation."""

    def __init__(
        self,
        driver_factory: Callable[[DatagramTransport, TradeRequest], FrlgWireDriver],
        *,
        tuning: FrlgProtocolTuning = FrlgProtocolTuning(),
    ) -> None:
        self._driver_factory = driver_factory
        self._tuning = tuning

    async def validate(self, request: TradeRequest) -> None:
        FrlgTeam.from_artifacts(request.team)
        if request.variant not in {None, "firered", "leafgreen"}:
            raise ProtocolStateError("FRLG variant must be firered or leafgreen")

    async def run(
        self,
        transport: DatagramTransport,
        request: TradeRequest,
        emit: EventSink,
    ) -> TradeResult:
        engine = FrlgTradeEngine(request, tuning=self._tuning)
        driver = self._driver_factory(transport, request)
        try:
            await driver.start()
            commands, events = engine.start(trio.current_time())
            await self._emit_and_send(driver, commands, events, emit)
            while engine.result is None:
                try:
                    with trio.fail_after(self._tuning.phase_timeout_seconds):
                        signal = await driver.receive()
                except trio.TooSlowError as error:
                    # The state machine owns the deadline and its public error
                    # vocabulary.  Do not leak Trio's scheduler exception from
                    # the game-facing API merely because the driver was quiet.
                    try:
                        engine.check_timeout(trio.current_time())
                    except TradeTimeoutError as timeout:
                        await emit_event(emit, TradeEvent(TradeEventKind.FAILED))
                        raise timeout from error
                    raise AssertionError("FRLG receive timeout preceded its deadline") from error
                commands, events = engine.receive(signal, trio.current_time())
                await self._emit_and_send(driver, commands, events, emit)
            result = engine.result
            assert result is not None
            return result
        finally:
            await driver.aclose()

    async def _emit_and_send(
        self,
        driver: FrlgWireDriver,
        commands: tuple[FrlgCommand, ...],
        events: tuple,
        emit: EventSink,
    ) -> None:
        for event in events:
            await emit_event(emit, event)
        for command in commands:
            await driver.send(command)
