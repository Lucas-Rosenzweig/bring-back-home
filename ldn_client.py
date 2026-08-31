"""Decode a captured LDN advertisement and join its network."""

import socket
from collections.abc import Iterable
from dataclasses import dataclass

from IEEE80211.ldn import LdnAdvertisement
from ldn_protocol import (
    ACCEPT_NONE,
    MACAddress,
    NetworkInfo,
    ParticipantInfo,
    decode_advertisement,
)
from Wifi.LdnStation import connect_ldn


@dataclass(frozen=True, slots=True)
class ActiveLdnConfig:
    phy: str
    station_interface: str
    nickname: bytes
    app_version: int
    passphrase: bytes
    pia_port: int = 12345


def decode_network(
    advertisement: LdnAdvertisement,
    channel: int,
    keys: dict[str, bytes],
    protocols: Iterable[int] = (1, 3),
) -> NetworkInfo:
    """Decrypt a raw advertisement with the project-owned LDN codec."""
    action = advertisement.raw_frame[24:]
    return decode_advertisement(
        action,
        MACAddress(advertisement.raw_frame[10:16]),
        channel,
        keys,
        tuple(protocols),
    )


def is_joinable(
    network: NetworkInfo,
    communication_id: int | None = None,
    scene_id: int | None = None,
) -> bool:
    return (
        (
            communication_id is None
            or int(network.local_communication_id) == communication_id
        )
        and (scene_id is None or int(network.scene_id) == scene_id)
        and int(network.accept_policy) != ACCEPT_NONE
        and int(network.num_participants) < int(network.max_participants)
    )


def display_network(network: NetworkInfo) -> None:
    print("LDN NetworkInfo déchiffré:")
    print(f"  Host               : {network.address}")
    print(f"  Channel            : {network.channel} ({network.band} GHz)")
    print(f"  Communication ID   : 0x{int(network.local_communication_id):016X}")
    print(f"  Scene ID           : {int(network.scene_id)}")
    print(f"  SSID               : {bytes(network.ssid).hex()}")
    print(f"  LDN version        : {int(network.version)}")
    print(f"  Application version: {int(network.app_version)}")
    print(f"  Accept policy      : {int(network.accept_policy)}")
    print(
        f"  Participants       : {int(network.num_participants)}/"
        f"{int(network.max_participants)}"
    )
    print(f"  Server random      : {bytes(network.server_random).hex()}")
    print(f"  Application data   : {bytes(network.application_data).hex(' ')}")


def _participant_name(participant: ParticipantInfo) -> str:
    value = participant.name
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").rstrip("\0")
    return str(value).rstrip("\0")


async def _observe_pia(interface: str, port: int) -> None:
    import trio

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_BINDTODEVICE,
        interface.encode() + b"\0",
    )
    receiver.bind(("0.0.0.0", port))
    receiver.setblocking(False)
    with receiver:
        print(f"Écoute PIA brute active sur UDP/{port}", flush=True)
        while True:
            await trio.lowlevel.wait_readable(receiver.fileno())
            try:
                payload, source = receiver.recvfrom(65535)
            except BlockingIOError:
                continue
            print(
                f"PIA brut {source[0]}:{source[1]} — {len(payload)} octets: "
                f"{payload.hex(' ')}",
                flush=True,
            )


async def connect_and_observe(
    config: ActiveLdnConfig,
    network: NetworkInfo,
    keys: dict[str, bytes],
) -> None:
    """Associate, authenticate, configure LDN IP, then observe raw PIA UDP."""
    import trio

    print(
        f"Association et authentification LDN sur {config.station_interface}...",
        flush=True,
    )
    async with connect_ldn(
        config.phy,
        config.station_interface,
        network,
        keys,
        config.passphrase,
        config.nickname,
        config.app_version,
    ) as connection:
        info = connection.info()
        local = connection.participant()
        print("Connexion LDN établie:", flush=True)
        print(
            f"  Local : {_participant_name(local)!r} {local.ip_address} {local.mac_address}"
        )
        for participant in info.participants:
            if participant.connected and participant.mac_address != local.mac_address:
                print(
                    f"  Pair  : {_participant_name(participant)!r} "
                    f"{participant.ip_address} {participant.mac_address}"
                )
        print(f"  Broadcast: {connection.broadcast_address()}", flush=True)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(connection.monitor)
            nursery.start_soon(
                _observe_pia,
                config.station_interface,
                config.pia_port,
            )
