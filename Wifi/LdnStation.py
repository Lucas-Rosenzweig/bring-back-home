"""Small nl80211 station client containing only what active LDN needs."""

from __future__ import annotations

import contextlib
import copy
import ipaddress
import random
import secrets
import socket
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import netlink
import trio
from netlink import nl80211, route

from ldn_protocol import (
    KeyDerivation,
    MACAddress,
    NetworkInfo,
    ParticipantInfo,
    decode_advertisement,
    encode_authentication_request,
    validate_authentication_response,
)

IFF_UP = 1
ETH_P_OUI = 0x88B7
WLAN_CIPHER_CCMP = 0x000FAC04
WLAN_AKM_PSK = 0x000FAC02
WLAN_STATUS_SUCCESS = 0
WLAN_EID_RSN = 48
WLAN_ACTION_FRAME_TYPE = 13 << 4

CHANNEL_FREQUENCIES = {
    1: 2412,
    6: 2437,
    11: 2462,
    36: 5180,
    40: 5200,
    44: 5220,
    48: 5240,
}
FREQUENCY_CHANNELS = {
    frequency: channel for channel, frequency in CHANNEL_FREQUENCIES.items()
}


@dataclass(frozen=True, slots=True)
class ActionEvent:
    source: MACAddress
    action: bytes
    channel: int
    frequency: int


@dataclass(frozen=True, slots=True)
class ControlEvent:
    source: MACAddress
    data: bytes


@dataclass(frozen=True, slots=True)
class DisassociationEvent:
    source: MACAddress


type StationEvent = ActionEvent | ControlEvent | DisassociationEvent


def infer_local_participant(
    network: NetworkInfo,
    address: MACAddress,
    nickname: bytes,
    app_version: int,
) -> tuple[NetworkInfo, int]:
    """Infer the slot allocated before an AUTH_SUCCESS response.

    LDN hosts allocate the first free participant slot and derive its final
    IPv4 octet from ``slot + 1``. This is only a fallback for hardware that
    filters the broadcast post-authentication advertisements in managed mode.
    """
    if not network.participants or not network.participants[0].connected:
        raise ValueError("the pre-authentication advertisement has no host slot")
    slot_limit = min(network.max_participants, len(network.participants))
    if slot_limit <= 1:
        raise ValueError("the advertised LDN network has no client slot")
    slot = next(
        (
            index
            for index in range(1, slot_limit)
            if not network.participants[index].connected
        ),
        None,
    )
    if slot is None:
        raise ValueError("the advertised LDN participant table is full")

    host_ip = ipaddress.ip_address(network.participants[0].ip_address)
    if not isinstance(host_ip, ipaddress.IPv4Address) or not host_ip.is_link_local:
        raise ValueError(f"unexpected LDN host address: {host_ip}")
    subnet = ipaddress.ip_network(f"{host_ip}/24", strict=False)
    local_ip = ipaddress.IPv4Address(int(subnet.network_address) + slot + 1)

    inferred = copy.deepcopy(network)
    inferred.participants[slot] = ParticipantInfo(
        ip_address=str(local_ip),
        mac_address=address,
        connected=True,
        name=nickname,
        app_version=app_version,
        platform=0,
    )
    inferred.num_participants = sum(
        participant.connected for participant in inferred.participants
    )
    return inferred, slot


def _rsn_element() -> bytes:
    body = bytearray(struct.pack("<H", 1))
    body += struct.pack(">I", WLAN_CIPHER_CCMP)
    body += struct.pack("<H", 1) + struct.pack(">I", WLAN_CIPHER_CCMP)
    body += struct.pack("<H", 1) + struct.pack(">I", WLAN_AKM_PSK)
    body += struct.pack("<H", 12)
    return bytes([WLAN_EID_RSN, len(body)]) + body


class StationInterface:
    def __init__(
        self,
        wlan: Any,
        router: Any,
        name: str,
        index: int,
        address: MACAddress,
        host: MACAddress,
    ) -> None:
        self.wlan = wlan
        self.router = router
        self.name = name
        self.index = index
        self.address = address
        self.host = host

    async def send_control(self, destination: MACAddress, data: bytes) -> None:
        await self.wlan.request(
            nl80211.NL80211_CMD_CONTROL_PORT_FRAME,
            {
                nl80211.NL80211_ATTR_IFINDEX: self.index,
                nl80211.NL80211_ATTR_FRAME: data,
                nl80211.NL80211_ATTR_MAC: bytes(destination),
                nl80211.NL80211_ATTR_CONTROL_PORT_ETHERTYPE: struct.pack(
                    "H", ETH_P_OUI
                ),
            },
        )

    async def receive(self) -> StationEvent:
        while True:
            message = await self.wlan.receive()
            attributes = message.attributes
            if message.type == nl80211.NL80211_CMD_FRAME:
                frame = bytes(attributes[nl80211.NL80211_ATTR_FRAME])
                if len(frame) < 24:
                    continue
                frame_control = int.from_bytes(frame[:2], "little")
                if ((frame_control >> 2) & 3) != 0 or ((frame_control >> 4) & 15) != 13:
                    continue
                frequency = int(attributes[nl80211.NL80211_ATTR_WIPHY_FREQ])
                channel = FREQUENCY_CHANNELS.get(frequency)
                if channel is None:
                    continue
                return ActionEvent(
                    MACAddress(frame[10:16]),
                    frame[24:],
                    channel,
                    frequency,
                )
            if message.type == nl80211.NL80211_CMD_CONTROL_PORT_FRAME:
                return ControlEvent(
                    MACAddress(bytes(attributes[nl80211.NL80211_ATTR_MAC])),
                    bytes(attributes[nl80211.NL80211_ATTR_FRAME]),
                )
            if message.type == nl80211.NL80211_CMD_DEL_STATION:
                return DisassociationEvent(
                    MACAddress(bytes(attributes[nl80211.NL80211_ATTR_MAC]))
                )

    async def authorize(self) -> None:
        flag = 1 << nl80211.NL80211_STA_FLAG_AUTHORIZED
        await self.wlan.request(
            nl80211.NL80211_CMD_SET_STATION,
            {
                nl80211.NL80211_ATTR_IFINDEX: self.index,
                nl80211.NL80211_ATTR_MAC: bytes(self.host),
                nl80211.NL80211_ATTR_STA_FLAGS2: struct.pack("II", flag, flag),
            },
        )

    async def add_address(self, local: str, broadcast: str) -> None:
        await self.router.add_address(
            socket.AF_INET,
            24,
            route.IFA_F_PERMANENT,
            route.RT_SCOPE_UNIVERSE,
            self.index,
            {
                route.IFA_LOCAL: socket.inet_aton(local),
                route.IFA_BROADCAST: socket.inet_aton(broadcast),
            },
        )

    async def add_neighbor(self, participant: ParticipantInfo) -> None:
        await self.router.add_neighbor(
            socket.AF_INET,
            self.index,
            route.NUD_PERMANENT,
            0,
            0,
            {
                route.NDA_DST: socket.inet_aton(participant.ip_address),
                route.NDA_LLADDR: bytes(participant.mac_address),
            },
        )


async def _wiphy_index(wlan: Any, phy: str) -> int:
    messages = await wlan.request(
        nl80211.NL80211_CMD_GET_WIPHY,
        flags=netlink.NLM_F_DUMP,
    )
    for message in messages:
        if message.attributes[nl80211.NL80211_ATTR_WIPHY_NAME] == phy:
            return int(message.attributes[nl80211.NL80211_ATTR_WIPHY])
    raise ValueError(f"unknown Wi-Fi PHY: {phy}")


async def _register_data_keys(
    wlan: Any,
    interface_index: int,
    host: MACAddress,
    key: bytes,
) -> None:
    common = {
        nl80211.NL80211_KEY_DATA: key,
        nl80211.NL80211_KEY_CIPHER: WLAN_CIPHER_CCMP,
    }
    await wlan.request(
        nl80211.NL80211_CMD_NEW_KEY,
        {
            nl80211.NL80211_ATTR_IFINDEX: interface_index,
            nl80211.NL80211_ATTR_MAC: bytes(host),
            nl80211.NL80211_ATTR_KEY: {
                **common,
                nl80211.NL80211_KEY_IDX: 0,
            },
        },
    )
    await wlan.request(
        nl80211.NL80211_CMD_NEW_KEY,
        {
            nl80211.NL80211_ATTR_IFINDEX: interface_index,
            nl80211.NL80211_ATTR_KEY: {
                **common,
                nl80211.NL80211_KEY_IDX: 1,
            },
        },
    )


@contextlib.asynccontextmanager
async def open_station(
    phy: str,
    interface_name: str,
    network: NetworkInfo,
    data_key: bytes,
) -> AsyncIterator[StationInterface]:
    async with nl80211.connect() as wlan, route.connect() as router:
        wlan.add_membership("mlme")
        phy_index = await _wiphy_index(wlan, phy)
        messages = await wlan.request(
            nl80211.NL80211_CMD_NEW_INTERFACE,
            {
                nl80211.NL80211_ATTR_WIPHY: phy_index,
                nl80211.NL80211_ATTR_IFNAME: interface_name,
                nl80211.NL80211_ATTR_IFTYPE: nl80211.NL80211_IFTYPE_STATION,
            },
        )
        attributes = messages[0].attributes
        interface_index = int(attributes[nl80211.NL80211_ATTR_IFINDEX])
        address = MACAddress(bytes(attributes[nl80211.NL80211_ATTR_MAC]))
        try:
            await router.update_link(
                socket.AF_UNSPEC,
                0,
                interface_index,
                IFF_UP,
                IFF_UP,
                {},
            )
            ipv6_control = Path(
                f"/proc/sys/net/ipv6/conf/{interface_name}/disable_ipv6"
            )
            if ipv6_control.exists():
                ipv6_control.write_text("1", encoding="ascii")

            await wlan.request(
                nl80211.NL80211_CMD_CONNECT,
                {
                    nl80211.NL80211_ATTR_IFINDEX: interface_index,
                    nl80211.NL80211_ATTR_SSID: network.ssid.hex().encode(),
                    nl80211.NL80211_ATTR_WIPHY_FREQ: CHANNEL_FREQUENCIES[
                        network.channel
                    ],
                    nl80211.NL80211_ATTR_AUTH_TYPE: (
                        nl80211.NL80211_AUTHTYPE_OPEN_SYSTEM
                    ),
                    nl80211.NL80211_ATTR_CONTROL_PORT: True,
                    nl80211.NL80211_ATTR_CONTROL_PORT_ETHERTYPE: struct.pack(
                        "H", ETH_P_OUI
                    ),
                    nl80211.NL80211_ATTR_CONTROL_PORT_OVER_NL80211: True,
                    nl80211.NL80211_ATTR_SOCKET_OWNER: True,
                    nl80211.NL80211_ATTR_CIPHER_SUITES_PAIRWISE: struct.pack(
                        "I", WLAN_CIPHER_CCMP
                    ),
                    nl80211.NL80211_ATTR_CIPHER_SUITE_GROUP: WLAN_CIPHER_CCMP,
                    nl80211.NL80211_ATTR_AKM_SUITES: struct.pack("I", WLAN_AKM_PSK),
                    nl80211.NL80211_ATTR_IE: _rsn_element(),
                    nl80211.NL80211_ATTR_PRIVACY: True,
                },
            )
            while True:
                message = await wlan.receive()
                if message.type != nl80211.NL80211_CMD_CONNECT:
                    continue
                status = int(message.attributes[nl80211.NL80211_ATTR_STATUS_CODE])
                if status != WLAN_STATUS_SUCCESS:
                    raise ConnectionError(
                        f"nl80211 association failed with status {status}"
                    )
                host = MACAddress(bytes(message.attributes[nl80211.NL80211_ATTR_MAC]))
                break
            await _register_data_keys(wlan, interface_index, host, data_key)
            await wlan.request(
                nl80211.NL80211_CMD_REGISTER_FRAME,
                {
                    nl80211.NL80211_ATTR_IFINDEX: interface_index,
                    nl80211.NL80211_ATTR_FRAME_TYPE: WLAN_ACTION_FRAME_TYPE,
                    nl80211.NL80211_ATTR_FRAME_MATCH: b"",
                },
            )
            kernel_mac_path = Path(f"/sys/class/net/{interface_name}/address")
            kernel_mac = (
                kernel_mac_path.read_text(encoding="ascii").strip()
                if kernel_mac_path.exists()
                else "unavailable"
            )
            print(
                "Diagnostic LDN — association nl80211 établie: "
                f"interface={interface_name} netlink_mac={address} "
                f"kernel_mac={kernel_mac} bssid={host} "
                f"channel={network.channel} "
                f"frequency={CHANNEL_FREQUENCIES[network.channel]}MHz",
                flush=True,
            )
            print(
                "Diagnostic LDN — clés CCMP installées et action frames enregistrées.",
                flush=True,
            )
            yield StationInterface(
                wlan,
                router,
                interface_name,
                interface_index,
                address,
                host,
            )
        finally:
            with trio.move_on_after(2, shield=True):
                try:
                    await wlan.request(
                        nl80211.NL80211_CMD_DISCONNECT,
                        {nl80211.NL80211_ATTR_IFINDEX: interface_index},
                    )
                except Exception:  # noqa: BLE001,S110 - continue interface cleanup
                    pass
                try:
                    await wlan.request(
                        nl80211.NL80211_CMD_DEL_INTERFACE,
                        {nl80211.NL80211_ATTR_IFINDEX: interface_index},
                    )
                except Exception:  # noqa: BLE001,S110 - outer radio lease also cleans it
                    pass


class LdnConnection:
    def __init__(
        self,
        station: StationInterface,
        network: NetworkInfo,
        keys: dict[str, bytes],
        nickname: bytes,
        app_version: int,
    ) -> None:
        self.station = station
        self.network = network
        self.keys = keys
        self.nickname = nickname
        self.app_version = app_version
        self.local_index = -1
        self.network_number = 0
        self.client_random = secrets.token_bytes(16)

    async def authenticate(self) -> None:
        request = encode_authentication_request(
            self.network,
            self.keys,
            self.client_random,
            self.nickname,
            self.app_version,
            random.randint(0, 0xFFFFFFFFFFFFFFFF),
            random.randint(0, 0xFFFFFFFFFFFFFFFF),
        )
        for attempt in range(1, 4):
            print(
                f"Diagnostic LDN — authentification, tentative {attempt}/3...",
                flush=True,
            )
            await self.station.send_control(self.network.address, request)
            with trio.move_on_after(0.7):
                while True:
                    event = await self.station.receive()
                    if (
                        isinstance(event, ControlEvent)
                        and event.source == self.network.address
                    ):
                        try:
                            validate_authentication_response(
                                event.data,
                                self.network,
                                self.keys,
                                self.client_random,
                            )
                        except ValueError:
                            continue
                        print(
                            "Diagnostic LDN — réponse d'authentification valide "
                            f"reçue de {event.source} (status=0).",
                            flush=True,
                        )
                        return
                    if isinstance(event, DisassociationEvent):
                        raise ConnectionError("host disassociated the LDN station")
        raise TimeoutError("LDN authentication timed out (wrong passphrase?)")

    async def initialize_network(self) -> None:
        await self.station.authorize()
        print(
            "Diagnostic LDN — station autorisée; attente de notre participant "
            f"(mac={self.station.address}) dans les advertisements post-auth...",
            flush=True,
        )
        updated: NetworkInfo | None = None
        event_count = 0
        action_count = 0
        host_action_count = 0
        decoded_count = 0
        decode_failure_count = 0
        last_decode_error: str | None = None
        last_participant_snapshot: tuple[tuple[int, str, str, str], ...] | None = None
        with trio.move_on_after(20):
            while True:
                event = await self.station.receive()
                event_count += 1
                if not isinstance(event, ActionEvent):
                    continue
                action_count += 1
                if event.source != self.network.address:
                    if action_count <= 3:
                        print(
                            "Diagnostic LDN — action frame d'une autre source: "
                            f"source={event.source} channel={event.channel} "
                            f"frequency={event.frequency}MHz size={len(event.action)}",
                            flush=True,
                        )
                    continue
                host_action_count += 1
                try:
                    candidate = decode_advertisement(
                        event.action,
                        event.source,
                        event.channel,
                        self.keys,
                        (self.network.protocol,),
                    )
                except ValueError as error:
                    decode_failure_count += 1
                    notes = "; ".join(getattr(error, "__notes__", []))
                    last_decode_error = f"{error}" + (f" ({notes})" if notes else "")
                    if decode_failure_count <= 3:
                        print(
                            "Diagnostic LDN — advertisement post-auth indécodable: "
                            f"channel={event.channel} frequency={event.frequency}MHz "
                            f"size={len(event.action)} error={last_decode_error}",
                            flush=True,
                        )
                    continue
                decoded_count += 1
                if not self.network.same_network(candidate):
                    raise ConnectionError(
                        "host changed to another LDN network: "
                        f"expected_channel={self.network.channel}, "
                        f"received_channel={candidate.channel}, "
                        f"expected_ssid={self.network.ssid.hex()}, "
                        f"received_ssid={candidate.ssid.hex()}"
                    )
                snapshot = tuple(
                    (
                        index,
                        str(participant.mac_address),
                        participant.ip_address,
                        participant.name.decode("utf-8", "replace"),
                    )
                    for index, participant in enumerate(candidate.participants)
                    if participant.connected
                )
                if snapshot != last_participant_snapshot:
                    rendered = ", ".join(
                        f"slot={index} mac={mac} ip={ip} name={name!r}"
                        for index, mac, ip, name in snapshot
                    )
                    print(
                        "Diagnostic LDN — advertisement post-auth décodée: "
                        f"channel={event.channel} frequency={event.frequency}MHz "
                        f"participants=[{rendered}]",
                        flush=True,
                    )
                    last_participant_snapshot = snapshot
                for index, participant in enumerate(candidate.participants):
                    if participant.mac_address == self.station.address:
                        updated = candidate
                        self.local_index = index
                        break
                if updated is not None:
                    break
        if updated is None:
            summary = (
                f"events={event_count}, actions={action_count}, "
                f"host_actions={host_action_count}, decoded={decoded_count}, "
                f"decode_failures={decode_failure_count}, "
                f"local_mac={self.station.address}"
            )
            if last_decode_error is not None:
                summary += f", last_decode_error={last_decode_error}"
            if host_action_count == 0:
                try:
                    updated, self.local_index = infer_local_participant(
                        self.network,
                        self.station.address,
                        self.nickname,
                        self.app_version,
                    )
                except ValueError as error:
                    raise TimeoutError(
                        "host did not advertise our LDN participant address and "
                        f"the fallback was rejected: {error} ({summary})"
                    ) from error
                participant = updated.participants[self.local_index]
                print(
                    "Diagnostic LDN — aucune advertisement post-auth reçue; "
                    "fallback déterministe activé après AUTH_SUCCESS: "
                    f"slot={self.local_index} mac={participant.mac_address} "
                    f"ip={participant.ip_address}",
                    flush=True,
                )
            else:
                raise TimeoutError(
                    "host did not advertise our LDN participant address "
                    f"within 2s ({summary})"
                )
        print(
            "Diagnostic LDN — participant local trouvé: "
            f"slot={self.local_index} mac={self.station.address} "
            f"ip={updated.participants[self.local_index].ip_address}",
            flush=True,
        )
        self.network = updated
        host = self.network.participants[0]
        self.network_number = int(host.ip_address.split(".")[2])
        local = self.participant()
        await self.station.add_address(local.ip_address, self.broadcast_address())
        for participant in self.network.participants:
            if participant.connected:
                await self.station.add_neighbor(participant)

    def info(self) -> NetworkInfo:
        return self.network

    def participant(self) -> ParticipantInfo:
        if self.local_index < 0:
            raise RuntimeError("LDN network is not initialized")
        return self.network.participants[self.local_index]

    def broadcast_address(self) -> str:
        return f"169.254.{self.network_number}.255"

    async def monitor(self) -> None:
        while True:
            event = await self.station.receive()
            if isinstance(event, DisassociationEvent):
                raise ConnectionError("LDN station was disconnected")
            if isinstance(event, ControlEvent):
                if event.data[:5] == b"\x00\x22\xaa\x01\x03":
                    reason = event.data[6] if len(event.data) > 6 else -1
                    raise ConnectionError(f"LDN host disconnected us (reason {reason})")
                continue
            if event.source != self.network.address:
                continue
            try:
                updated = decode_advertisement(
                    event.action,
                    event.source,
                    event.channel,
                    self.keys,
                    (self.network.protocol,),
                )
            except ValueError:
                continue
            if not self.network.same_network(updated):
                raise ConnectionError("LDN network identity changed")
            previous = self.network
            self.network = updated
            if (
                updated.num_participants != previous.num_participants
                or updated.accept_policy != previous.accept_policy
                or updated.application_data != previous.application_data
            ):
                print(
                    "Advertisement LDN mise à jour: "
                    f"{updated.num_participants}/{updated.max_participants} participants",
                    flush=True,
                )


@contextlib.asynccontextmanager
async def connect_ldn(
    phy: str,
    interface_name: str,
    network: NetworkInfo,
    keys: dict[str, bytes],
    passphrase: bytes,
    nickname: bytes,
    app_version: int,
) -> AsyncIterator[LdnConnection]:
    data_key = KeyDerivation(keys, network.protocol).data_key(
        network.server_random,
        passphrase,
    )
    async with open_station(
        phy,
        interface_name,
        network,
        data_key,
    ) as station:
        connection = LdnConnection(station, network, keys, nickname, app_version)
        await connection.authenticate()
        await connection.initialize_network()
        yield connection
