"""Game-neutral orchestration over an established datagram transport."""

from __future__ import annotations

import inspect

from pokemon_trade.api import EventSink, TradeEvent, TradeEventKind, TradeRequest, TradeResult
from pokemon_trade.registry import GameRegistry
from pokemon_trade.transport.base import DatagramTransport


async def emit_event(sink: EventSink, event: TradeEvent) -> None:
    result = sink(event)
    if inspect.isawaitable(result):
        await result


async def run_trade(
    registry: GameRegistry,
    transport: DatagramTransport,
    request: TradeRequest,
    emit: EventSink,
    *,
    game_id: str | None = None,
) -> TradeResult:
    """Resolve, validate and run a plugin through the one public path."""
    descriptor = registry.resolve(transport.session, game_id)
    client = descriptor.create_client()
    await client.validate(request)
    await emit_event(emit, TradeEvent(TradeEventKind.LDN_READY))
    return await client.run(transport, request, emit)
