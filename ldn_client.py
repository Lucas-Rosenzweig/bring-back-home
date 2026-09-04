"""Decode LDN advertisements and determine whether a network is joinable."""

from collections.abc import Iterable

from IEEE80211.ldn import LdnAdvertisement
from ldn_protocol import (
    ACCEPT_NONE,
    MACAddress,
    NetworkInfo,
    decode_advertisement,
)


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
