"""Private LDN discovery and passphrase loading for the trade CLI."""

from __future__ import annotations

import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from IEEE80211.ldn import parse_ldn_advertisement
from ldn_client import decode_network, is_joinable
from ldn_protocol import NetworkInfo
from Wifi.LinuxMonitor import LinuxMonitor


@dataclass(frozen=True, slots=True)
class LdnDiscoveryConfig:
    phy: str
    monitor_interface: str
    channels: tuple[int, ...]
    dwell_seconds: float
    timeout_seconds: float
    communication_ids: frozenset[int]
    scene_id: int | None = None


@dataclass(frozen=True, slots=True)
class Passphrases:
    by_communication_id: dict[int, bytes]
    fallback: bytes | None = None

    def get(self, communication_id: int) -> bytes | None:
        return self.by_communication_id.get(communication_id, self.fallback)


def _decode_passphrase(value: str) -> bytes:
    compact = "".join(value.split())
    try:
        decoded = bytes.fromhex(compact)
    except ValueError:
        return value.encode("utf-8")
    return decoded if decoded else value.encode("utf-8")


def read_passphrases(path: Path | None, environment_variable: str) -> Passphrases:
    """Load a fallback secret or a communication-ID-indexed TOML catalogue."""
    environment_value = os.environ.get(environment_variable)
    if environment_value is not None:
        return Passphrases({}, _decode_passphrase(environment_value))
    if path is None:
        return Passphrases({})
    expanded = path.expanduser()
    if not expanded.is_file():
        raise FileNotFoundError(f"passphrase file not found: {expanded}")
    if expanded.suffix.lower() != ".toml":
        return Passphrases({}, expanded.read_bytes().strip())

    document = tomllib.loads(expanded.read_text(encoding="utf-8"))
    values = document.get("passphrases")
    if not isinstance(values, dict) or not values:
        raise ValueError(f"missing non-empty [passphrases] table in {expanded}")
    parsed: dict[int, bytes] = {}
    for raw_id, raw_passphrase in values.items():
        if not isinstance(raw_id, str) or not isinstance(raw_passphrase, str):
            raise TypeError("passphrase IDs and values must be TOML strings")
        try:
            communication_id = int(raw_id.removeprefix("0x"), 16)
        except ValueError as error:
            raise ValueError(
                f"invalid communication ID in {expanded}: {raw_id}"
            ) from error
        parsed[communication_id] = _decode_passphrase(raw_passphrase)
    return Passphrases(parsed)


def discover_target_network(
    config: LdnDiscoveryConfig,
    keys: dict[str, bytes],
    passphrases: Passphrases,
) -> tuple[NetworkInfo, bytes]:
    """Find a joinable session belonging to the selected Pokémon game."""
    deadline = time.monotonic() + config.timeout_seconds
    reported_decryption_failure = False
    reported_unjoinable: set[tuple[int, int, int]] = set()
    reported_ignored: set[tuple[int, int, str]] = set()
    with LinuxMonitor(
        mon_iface=config.monitor_interface,
        phy=config.phy,
        initial_channel=config.channels[0],
        replace_existing=False,
    ) as monitor:
        print(
            f"Interface {monitor.mon_iface} prête sur le canal {monitor.current_channel}",
            flush=True,
        )
        monitor.start_channel_hopping(config.channels, dwell_seconds=config.dwell_seconds)
        print("Recherche LDN sur " + ", ".join(map(str, config.channels)) + "...", flush=True)

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
            if communication_id not in config.communication_ids:
                reason = "jeu différent"
            elif config.scene_id is not None and scene_id != config.scene_id:
                reason = "scene ID différent"
            else:
                reason = ""
            passphrase = passphrases.get(communication_id)
            if passphrase is None:
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
            if not is_joinable(network, scene_id=config.scene_id):
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
            assert passphrase is not None
            return network, passphrase

    raise TimeoutError(
        f"no joinable LDN session found after {config.timeout_seconds:.1f}s"
    )
