"""Composition of the FRLG live driver over an established LDN connection."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from pathlib import Path

import trio

from pokemon_trade.api import EventSink, TradeRequest, TradeResult
from pokemon_trade.errors import PeerDisconnectedError
from pokemon_trade.games.frlg.driver import FrlgLiveWireConfig
from pokemon_trade.games.frlg.game_data import build_rfu_game_data, build_trainer_card
from pokemon_trade.games.frlg.identity import FrlgIdentity, LinkPlayerRecord
from pokemon_trade.games.frlg.pokemon import FrlgTeam
from pokemon_trade.games.frlg.replay import FrlgReplayEntropy
from pokemon_trade.games.frlg.trade_driver import FrlgTradePiaRfuDriver, FrlgTradeWireConfig
from pokemon_trade.games.frlg.trade.engine import FrlgProtocolTuning
from pokemon_trade.registry import GameRegistry
from pokemon_trade.service import run_trade
from pokemon_trade.transport.base import DatagramTransport, SessionContext
from pokemon_trade.transport.ldn_udp import LdnUdpTransport
from pokemon_trade.transport.capture import CaptureTransport

# FRLG's PIA title key is protocol material, not a console secret.  Console
# prod.keys and LDN passphrases remain inputs to the legacy LDN connection.
FRLG_PIA_GAME_KEY = bytes.fromhex("83CA7FAB734C34633B10183526C1E85B")


def build_trade_wire_config(
    session: SessionContext,
    request: TradeRequest,
    identity: FrlgIdentity,
    replay_entropy: FrlgReplayEntropy | None = None,
    clock: Callable[[], float] = time.monotonic,
    animation_frames: int = 1935,
    disconnect_after_trade: bool = False,
) -> FrlgTradeWireConfig:
    """Derive only ephemeral follower values from a connected LDN session."""
    local_constant_id = bytes.fromhex(session.local.mac_address.replace(":", ""))
    if len(local_constant_id) != 6:
        raise ValueError("LDN local MAC must contain six octets")
    connect_id = replay_entropy.rfu_connect_id if replay_entropy is not None else secrets.token_bytes(2)
    while connect_id == b"\0\0":
        connect_id = secrets.token_bytes(2)
    team = FrlgTeam.from_artifacts(request.team)
    return FrlgTradeWireConfig(
        FrlgLiveWireConfig(
            game_key=FRLG_PIA_GAME_KEY,
            pia_constant_id=local_constant_id,
            player_name=identity.name,
            rfu_connect_id=connect_id,
            rfu_game_data=build_rfu_game_data(identity),
            random_nonce=(replay_entropy.session_nonce if replay_entropy is not None else None),
            local_variable_id=(replay_entropy.local_variable_id if replay_entropy is not None else None),
            packet_nonces=(replay_entropy.packet_nonces if replay_entropy is not None else ()),
            clock=clock,
        ),
        LinkPlayerRecord(identity).block(),
        build_trainer_card(identity, team),
        animation_frames=animation_frames,
        disconnect_after_trade=disconnect_after_trade,
    )


def frlg_live_registry(
    identity: FrlgIdentity,
    *,
    tuning: FrlgProtocolTuning = FrlgProtocolTuning(),
    replay_entropy: FrlgReplayEntropy | None = None,
    clock: Callable[[], float] = time.monotonic,
    animation_frames: int = 1935,
    disconnect_after_trade: bool = False,
) -> GameRegistry:
    """Build the one registered FRLG plugin factory for a run."""
    from pokemon_trade.games.frlg.descriptor import frlg_descriptor

    def create_driver(transport: DatagramTransport, request: TradeRequest) -> FrlgTradePiaRfuDriver:
        return FrlgTradePiaRfuDriver(
            transport,
            request,
            build_trade_wire_config(
                transport.session,
                request,
                identity,
                replay_entropy=replay_entropy,
                clock=clock,
                animation_frames=animation_frames,
                disconnect_after_trade=disconnect_after_trade,
            ),
        )

    return GameRegistry((frlg_descriptor(create_driver, tuning=tuning),))


async def run_connected_trade(
    connection: object,
    interface: str,
    request: TradeRequest,
    identity: FrlgIdentity,
    emit: EventSink,
    *,
    game_id: str | None = None,
    capture_path: Path | None = None,
    tuning: FrlgProtocolTuning = FrlgProtocolTuning(),
    disconnect_after_trade: bool = False,
) -> TradeResult:
    """Run exactly one FRLG client while the established LDN link is monitored."""
    live_transport = await LdnUdpTransport.open(connection, interface)  # type: ignore[arg-type]
    transport: DatagramTransport = live_transport
    if capture_path is not None:
        transport = CaptureTransport.to_path(live_transport, capture_path)
    try:
        trade_error: BaseException | None = None
        monitor_error: BaseException | None = None
        result: TradeResult | None = None
        finished = trio.Event()

        async def run_client() -> None:
            nonlocal result, trade_error
            try:
                result = await run_trade(
                    frlg_live_registry(
                        identity,
                        tuning=tuning,
                        disconnect_after_trade=disconnect_after_trade,
                    ),
                    transport,
                    request,
                    emit,
                    game_id=game_id,
                )
            except trio.Cancelled:
                raise
            except BaseException as error:
                trade_error = error
            finally:
                finished.set()

        async def watch_connection() -> None:
            nonlocal monitor_error
            monitor = getattr(connection, "monitor")
            try:
                await monitor()
            except trio.Cancelled:
                raise
            except BaseException as error:
                monitor_error = error
            else:
                monitor_error = ConnectionError("LDN connection monitor stopped")
            finally:
                finished.set()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(watch_connection)
            nursery.start_soon(run_client)
            await finished.wait()
            nursery.cancel_scope.cancel()
        if monitor_error is not None:
            raise PeerDisconnectedError("LDN station disconnected during FRLG trade") from monitor_error
        if trade_error is not None:
            raise trade_error
        assert result is not None
        return result
    finally:
        await transport.aclose()
