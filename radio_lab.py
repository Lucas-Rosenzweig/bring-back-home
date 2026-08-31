import argparse
import os
import signal
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from IEEE80211.ldn import parse_ldn_advertisement
from ldn_client import (
    ActiveLdnConfig,
    connect_and_observe,
    decode_network,
    display_network,
    is_joinable,
)
from ldn_protocol import NetworkInfo, load_keys
from Wifi.LinuxMonitor import LinuxMonitor
from Wifi.LinuxRadioLease import LinuxRadioLease

DEFAULT_CHANNELS = (1, 6, 11, 36, 40, 44, 48)
DEFAULT_DWELL_SECONDS = 0.110
PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Passphrases:
    by_communication_id: dict[int, bytes]
    fallback: bytes | None = None

    def get(self, communication_id: int) -> bytes | None:
        return self.by_communication_id.get(communication_id, self.fallback)


def _integer(value: str) -> int:
    return int(value, 0)


def _channels(value: str) -> tuple[int, ...]:
    try:
        channels = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "channels must be comma-separated integers"
        ) from error
    if not channels or any(channel <= 0 for channel in channels):
        raise argparse.ArgumentTypeError("channels must be positive integers")
    return channels


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover, decrypt and join a Nintendo Switch LDN session, then "
            "observe raw PIA datagrams."
        )
    )
    parser.add_argument(
        "--keys",
        type=Path,
        default=PROJECT_ROOT / ".switch" / "prod.keys",
        help="path to prod.keys (default: .switch/prod.keys)",
    )
    parser.add_argument("--phy", default="phy0")
    parser.add_argument("--monitor-interface", default="mon0")
    parser.add_argument("--station-interface", default="ldnclient")
    parser.add_argument("--channels", type=_channels, default=DEFAULT_CHANNELS)
    parser.add_argument("--dwell", type=float, default=DEFAULT_DWELL_SECONDS)
    parser.add_argument("--discovery-timeout", type=float, default=30.0)
    parser.add_argument(
        "--communication-id",
        type=_integer,
        help="optional communication ID filter (for example 0x0100...)",
    )
    parser.add_argument("--scene-id", type=_integer, help="optional scene ID filter")
    parser.add_argument(
        "--app-version",
        type=_integer,
        help="client application version (default: value advertised by the host)",
    )
    parser.add_argument("--nickname", default="SVPC")
    parser.add_argument("--pia-port", type=int, default=12345)
    parser.add_argument(
        "--passphrase-env",
        default="LDN_PASSPHRASE",
        help="environment variable containing the LDN passphrase",
    )
    parser.add_argument(
        "--passphrase-file",
        type=Path,
        help="file containing the LDN passphrase (environment takes precedence)",
    )
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        help="decrypt and display NetworkInfo without joining",
    )
    args = parser.parse_args(argv)
    if args.dwell <= 0:
        parser.error("--dwell must be greater than zero")
    if args.discovery_timeout <= 0:
        parser.error("--discovery-timeout must be greater than zero")
    if not 1 <= args.pia_port <= 65535:
        parser.error("--pia-port must be between 1 and 65535")
    if len(args.nickname.encode("utf-8")) > 32:
        parser.error("--nickname must fit in 32 UTF-8 bytes")
    return args


def _terminate(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def _capture_target_network(
    args: argparse.Namespace,
    keys: dict[str, bytes],
    passphrases: Passphrases,
) -> tuple[NetworkInfo, bytes | None]:
    deadline = time.monotonic() + args.discovery_timeout
    reported_decryption_failure = False
    reported_unjoinable: set[tuple[int, int, int]] = set()
    reported_ignored: set[tuple[int, int, str]] = set()
    with LinuxMonitor(
        mon_iface=args.monitor_interface,
        phy=args.phy,
        initial_channel=args.channels[0],
        replace_existing=False,
    ) as monitor:
        print(
            f"Interface {monitor.mon_iface} prête sur le canal "
            f"{monitor.current_channel}",
            flush=True,
        )
        monitor.start_channel_hopping(args.channels, dwell_seconds=args.dwell)
        print(
            "Recherche LDN sur " + ", ".join(map(str, args.channels)) + "...",
            flush=True,
        )

        while time.monotonic() < deadline:
            capture = monitor.scan()
            if capture is None:
                continue
            mac_frame, channel = capture
            if channel is None:
                continue

            try:
                advertisement = parse_ldn_advertisement(mac_frame)
            except ValueError:
                continue
            if advertisement is None:
                continue
            try:
                network = decode_network(advertisement, channel, keys)
            except ValueError as error:
                if not reported_decryption_failure:
                    details = "; ".join(getattr(error, "__notes__", []))
                    print(
                        "Advertisement LDN détectée mais impossible à déchiffrer: "
                        f"{error}" + (f" ({details})" if details else ""),
                        flush=True,
                    )
                    reported_decryption_failure = True
                continue

            communication_id = int(network.local_communication_id)
            scene_id = int(network.scene_id)
            if (
                args.communication_id is not None
                and communication_id != args.communication_id
            ):
                reason = "communication ID différent"
            elif args.scene_id is not None and scene_id != args.scene_id:
                reason = "scene ID différent"
            else:
                reason = ""
            passphrase = passphrases.get(communication_id)
            if not args.discovery_only and passphrase is None:
                reason = "aucune passphrase correspondante"
            if reason:
                signature = (communication_id, scene_id, reason)
                if signature not in reported_ignored:
                    print(
                        "Session LDN ignorée: "
                        f"0x{communication_id:016X}/scene={scene_id} ({reason})",
                        flush=True,
                    )
                    reported_ignored.add(signature)
                continue
            if not is_joinable(network, args.communication_id, args.scene_id):
                state = (
                    int(network.num_participants),
                    int(network.max_participants),
                    int(network.accept_policy),
                )
                if state not in reported_unjoinable:
                    print(
                        "Session cible trouvée mais non joignable "
                        f"({state[0]}/{state[1]}, policy={state[2]})",
                        flush=True,
                    )
                    reported_unjoinable.add(state)
                continue

            monitor.stop_channel_hopping()
            monitor.set_channel(channel)
            print(f"Session cible trouvée sur le canal {channel}.", flush=True)
            display_network(network)
            return network, passphrase

    raise TimeoutError(
        f"no joinable LDN session found after {args.discovery_timeout:.1f}s"
    )


def _decode_passphrase(value: str) -> bytes:
    compact = "".join(value.split())
    try:
        decoded = bytes.fromhex(compact)
    except ValueError:
        return value.encode("utf-8")
    return decoded if decoded else value.encode("utf-8")


def _read_passphrases(args: argparse.Namespace) -> Passphrases:
    environment_value = os.environ.get(args.passphrase_env)
    if environment_value is not None:
        return Passphrases({}, _decode_passphrase(environment_value))
    if args.passphrase_file is not None:
        path = args.passphrase_file.expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"passphrase file not found: {path}")
        if path.suffix.lower() == ".toml":
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            values = document.get("passphrases")
            if not isinstance(values, dict) or not values:
                raise ValueError(f"missing non-empty [passphrases] table in {path}")
            parsed: dict[int, bytes] = {}
            for raw_id, raw_passphrase in values.items():
                if not isinstance(raw_id, str) or not isinstance(raw_passphrase, str):
                    raise TypeError("passphrase IDs and values must be TOML strings")
                try:
                    communication_id = int(raw_id.removeprefix("0x"), 16)
                except ValueError as error:
                    raise ValueError(
                        f"invalid communication ID in {path}: {raw_id}"
                    ) from error
                parsed[communication_id] = _decode_passphrase(raw_passphrase)
            return Passphrases(parsed)
        return Passphrases({}, path.read_bytes().strip())
    return Passphrases({})


def main(argv: list[str] | None = None) -> None:
    args = _arguments(argv)
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    keys_path = args.keys.expanduser()
    if not keys_path.is_file():
        raise FileNotFoundError(f"prod.keys not found: {keys_path}")

    import trio

    keys = load_keys(keys_path)
    passphrases = _read_passphrases(args)
    if (
        not args.discovery_only
        and not passphrases.by_communication_id
        and passphrases.fallback is None
    ):
        raise RuntimeError(
            f"set {args.passphrase_env}, pass --passphrase-file, or use "
            "--discovery-only"
        )

    transient_interfaces = {
        args.monitor_interface,
        args.station_interface,
    }
    try:
        with LinuxRadioLease(args.phy, transient_interfaces):
            network, passphrase = _capture_target_network(args, keys, passphrases)
            if args.discovery_only:
                print("Découverte terminée; aucune association demandée.")
                return

            assert passphrase is not None
            config = ActiveLdnConfig(
                phy=args.phy,
                station_interface=args.station_interface,
                nickname=args.nickname.encode("utf-8"),
                app_version=(
                    args.app_version
                    if args.app_version is not None
                    else int(network.app_version)
                ),
                passphrase=passphrase,
                pia_port=args.pia_port,
            )
            trio.run(connect_and_observe, config, network, keys)
    except KeyboardInterrupt:
        print("Arrêt demandé; restauration des interfaces Wi-Fi.")


if __name__ == "__main__":
    main()
