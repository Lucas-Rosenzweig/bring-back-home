"""Thin command-line façade for the typed Pokémon trade library."""

from __future__ import annotations

import argparse
from pathlib import Path

import trio

from ldn_protocol import load_keys
from pokemon_trade.api import TradeEvent, TradeRequest, TradeResult, TradeStatus
from pokemon_trade.artifacts import PokemonArtifact, export_artifacts
from pokemon_trade.errors import TradeError
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant
from pokemon_trade.games.frlg.descriptor import FRLG_OBSERVED_COMMUNICATION_IDS
from pokemon_trade.games.frlg.driver import FRLG_VBLANK_SECONDS
from pokemon_trade.games.frlg.live import (
    FRLG_PIA_GAME_KEY,
    frlg_live_registry,
    run_connected_trade,
)
from pokemon_trade.games.frlg.pokemon import FrlgTeam
from pokemon_trade.games.frlg.replay import extract_frlg_replay_entropy
from pokemon_trade.games.frlg.trade.engine import (
    DEFAULT_FRLG_PHASE_TIMEOUT_SECONDS,
    FrlgProtocolTuning,
)
from pokemon_trade.service import run_trade
from pokemon_trade.transport.replay import ReplayTransport

PROJECT_ROOT = Path(__file__).resolve().parent


def _slots(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("slots must be comma-separated integers") from error


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Pokémon follower trade.")
    parser.add_argument("team", nargs="+", type=Path, metavar="PK3", help="one to six .pk3 files")
    parser.add_argument("--game", choices=("firered", "leafgreen"), required=True)
    parser.add_argument("--trainer-id", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--secret-id", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--name", required=True, help="one to seven Gen III trainer-name characters")
    parser.add_argument("--trades", type=int)
    parser.add_argument("--slots", type=_slots)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--replay", type=Path, help="synthetic JSONL transport capture; needs no privileges")
    parser.add_argument("--capture", type=Path, help="new local 0600 JSONL live capture; contains sensitive session data")
    parser.add_argument("--keys", type=Path, default=PROJECT_ROOT / ".switch" / "prod.keys")
    parser.add_argument("--passphrase-file", type=Path)
    parser.add_argument("--passphrase-env", default="LDN_PASSPHRASE")
    parser.add_argument("--phy", default="phy0")
    parser.add_argument("--monitor-interface", default="mon0")
    parser.add_argument("--station-interface", default="ldnclient")
    parser.add_argument("--channels", default="1,6,11,36,40,44,48")
    parser.add_argument("--dwell", type=float, default=0.110)
    parser.add_argument("--discovery-timeout", type=float, default=30.0)
    parser.add_argument(
        "--phase-timeout", type=float, default=DEFAULT_FRLG_PHASE_TIMEOUT_SECONDS,
        help="maximum seconds to wait for each interactive FRLG trade phase",
    )
    parser.add_argument("--scene-id", type=lambda value: int(value, 0))
    parser.add_argument("--app-version", type=lambda value: int(value, 0))
    parser.add_argument(
        "--disconnect-after-trade",
        action="store_true",
        help=(
            "disconnect immediately after the final FRLG save completes, "
            "skipping the graceful room-exit handshake"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print non-sensitive run and protocol timing settings",
    )
    args = parser.parse_args(argv)
    if not 1 <= len(args.team) <= 6:
        parser.error("supply one to six .pk3 files")
    if args.trades is not None and not 1 <= args.trades <= 6:
        parser.error("--trades must be between one and six")
    if args.dwell <= 0 or args.discovery_timeout <= 0 or args.phase_timeout <= 0:
        parser.error("discovery timing values must be positive")
    if args.replay is not None and args.capture is not None:
        parser.error("--capture is only available for a live run")
    try:
        args.channels = tuple(int(part) for part in args.channels.split(","))
    except ValueError:
        parser.error("--channels must contain comma-separated integers")
    if not args.channels or any(channel <= 0 for channel in args.channels):
        parser.error("--channels must contain positive integers")
    return args


def _request(args: argparse.Namespace) -> TradeRequest:
    artifacts: list[PokemonArtifact] = []
    for path in args.team:
        try:
            artifacts.append(PokemonArtifact("pk3", path.read_bytes(), 3))
        except OSError as error:
            raise ValueError(f"cannot read offered .pk3: {path}") from error
    return TradeRequest(
        tuple(artifacts),
        trade_count=args.trades,
        offered_slots=args.slots or (),
        variant=args.game,
    )


def _identity(args: argparse.Namespace) -> FrlgIdentity:
    return FrlgIdentity(args.trainer_id, args.secret_id, args.name, FrlgVariant(args.game))


def _emit(event: TradeEvent) -> None:
    suffix = f" #{event.round_index}" if event.round_index is not None else ""
    print(f"{event.kind}{suffix}", flush=True)


def _display_diagnostics(args: argparse.Namespace, request: TradeRequest) -> None:
    """Print useful run settings without identity, session, or Pokémon data."""
    mode = "replay" if args.replay is not None else "live"
    slots = request.offered_slots
    print(
        "diagnostic: "
        f"mode={mode}, game={args.game}, "
        f"trades={request.trade_count}, slots={','.join(map(str, slots))}, "
        f"disconnect_after_trade={args.disconnect_after_trade}, "
        f"phase_timeout={args.phase_timeout:.3f}s, "
        f"vblank={FRLG_VBLANK_SECONDS:.9f}s",
        flush=True,
    )


async def _run_replay(args: argparse.Namespace, request: TradeRequest, identity: FrlgIdentity):
    assert args.replay is not None
    transport = ReplayTransport.from_path(
        args.replay,
        max_clock_step_seconds=FRLG_VBLANK_SECONDS,
    )
    try:
        entropy = extract_frlg_replay_entropy(transport, FRLG_PIA_GAME_KEY)
        result = await run_trade(
            frlg_live_registry(
                identity,
                replay_entropy=entropy,
                clock=transport.current_time,
                disconnect_after_trade=args.disconnect_after_trade,
            ),
            transport,
            request,
            _emit,
            game_id="frlg",
        )
        transport.assert_finished()
        return result
    finally:
        await transport.aclose()


async def _run_live(args: argparse.Namespace, network, passphrase: bytes, keys, request, identity):
    from Wifi.LdnStation import connect_ldn

    app_version = args.app_version if args.app_version is not None else int(network.app_version)
    try:
        async with connect_ldn(
            args.phy, args.station_interface, network, keys, passphrase,
            identity.name.encode("utf-8"), app_version,
        ) as connection:
            return await run_connected_trade(
                connection, args.station_interface, request, identity, _emit,
                game_id="frlg", capture_path=args.capture,
                tuning=FrlgProtocolTuning(args.phase_timeout),
                disconnect_after_trade=args.disconnect_after_trade,
            )
    except BaseExceptionGroup as error:
        trade_error = _find_trade_error(error)
        if trade_error is not None:
            raise trade_error from None
        raise


def _find_trade_error(error: BaseException) -> TradeError | None:
    if isinstance(error, TradeError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            found = _find_trade_error(nested)
            if found is not None:
                return found
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        request = _request(args)
        # Validate the offered bytes before taking control of the radio.  The
        # plugin repeats this check at the public service boundary, but doing it
        # here prevents an input typo from joining a real lobby at all.
        FrlgTeam.from_artifacts(request.team)
        identity = _identity(args)
        if args.verbose:
            _display_diagnostics(args, request)
        result: TradeResult | None = None
        if args.replay is not None:
            from trio.testing import MockClock

            result = trio.run(
                _run_replay,
                args,
                request,
                identity,
                clock=MockClock(autojump_threshold=0),
            )
        else:
            from Wifi.LinuxRadioLease import LinuxRadioLease
            from pokemon_trade.transport.ldn_discovery import (
                LdnDiscoveryConfig,
                discover_target_network,
                read_passphrases,
            )

            if not args.keys.is_file():
                raise FileNotFoundError(f"prod.keys not found: {args.keys}")
            passphrases = read_passphrases(args.passphrase_file, args.passphrase_env)
            if not passphrases.by_communication_id and passphrases.fallback is None:
                raise RuntimeError("set a passphrase environment variable or use --passphrase-file")
            keys = load_keys(args.keys)
            with LinuxRadioLease(args.phy, {args.monitor_interface, args.station_interface}):
                network, passphrase = discover_target_network(
                    LdnDiscoveryConfig(
                        phy=args.phy,
                        monitor_interface=args.monitor_interface,
                        channels=args.channels,
                        dwell_seconds=args.dwell,
                        timeout_seconds=args.discovery_timeout,
                        communication_ids=FRLG_OBSERVED_COMMUNICATION_IDS,
                        scene_id=args.scene_id,
                    ),
                    keys,
                    passphrases,
                )
                result = trio.run(_run_live, args, network, passphrase, keys, request, identity)
    except (OSError, RuntimeError, TradeError) as error:
        print(f"error: {error}", flush=True)
        return 1
    assert result is not None
    if result.received:
        for path in export_artifacts(result.received, args.output_dir):
            print(f"exported {path}", flush=True)
    if result.error:
        print(f"error: {result.error}", flush=True)
    print(result.status, flush=True)
    return 0 if result.status is TradeStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
