"""PIA Net/Session/RTT negotiation for a follower joining an FRLG mesh."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from pokemon_trade.errors import MalformedDatagramError, ProtocolStateError


class PiaProtocol(IntEnum):
    NET = 1
    RTT = 3
    RELIABLE = 10
    SESSION = 13


class PiaSessionPhase(StrEnum):
    WAITING_FOR_NET = "waiting_for_net"
    WAITING_FOR_LIVE_TRAFFIC = "waiting_for_live_traffic"
    CONNECTED = "connected"


@dataclass(frozen=True, slots=True)
class PiaMessage:
    protocol: PiaProtocol
    payload: bytes


@dataclass(frozen=True, slots=True)
class PiaOutbound:
    message: PiaMessage
    destination_variable_id: int
    source_variable_id: int
    footer_variable_id: int | None
    compressed: bool = False
    establishing: bool = False


def parse_net(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 4:
        raise MalformedDatagramError("truncated PIA Net message")
    size = int.from_bytes(payload[2:4], "big")
    if size > len(payload) - 4:
        raise MalformedDatagramError("PIA Net message size mismatch")
    # PIA's Net control header does not count every control trailer in its
    # advertised size (notably the four-byte transaction sequence).  Preserve
    # that trailer for the per-message handler, which owns its structure.
    return payload[0], payload[1], payload[4:]


def build_net_reply(message_type: int, sequence: int) -> bytes:
    return bytes((1, message_type, 0, 0)) + sequence.to_bytes(4, "big")


def parse_connection_request(payload: bytes) -> tuple[int, bytes, int]:
    _, message_type, body = parse_net(payload)
    if message_type != 0x11 or len(body) < 12:
        raise MalformedDatagramError("invalid PIA Net connection request")
    return (
        int.from_bytes(body[4:6], "big"),
        bytes(body[6:12]),
        int.from_bytes(body[:4], "big"),
    )


def build_session_join(
    *,
    local_constant_id: bytes,
    local_variable_id: int,
    local_ip: str,
    host_constant_id: bytes,
    host_variable_id: int,
    player_name: str,
    random_nonce: bytes,
    app_version: int,
    protocols: tuple[tuple[int, int], ...],
    player_id: bytes,
) -> bytes:
    """Build the documented Session(new) join message with explicit identities."""
    if len(local_constant_id) != 6 or len(host_constant_id) != 6:
        raise ValueError("PIA constant IDs must contain six bytes")
    if len(random_nonce) != 4 or len(player_id) != 16:
        raise ValueError("invalid PIA join nonce or player ID")
    if not 0 <= app_version <= 0xFFFF or any(not 0 <= item <= 0xFF for pair in protocols for item in pair):
        raise ValueError("invalid PIA join protocol metadata")
    encoded_name = player_name.encode("utf-8")[:20]
    try:
        address = ipaddress.IPv4Address(local_ip).packed
    except ipaddress.AddressValueError as error:
        raise ValueError("PIA join requires an IPv4 local address") from error
    result = bytearray((0, len(protocols)))
    for protocol, version in protocols:
        result += bytes((protocol, version))
    result += app_version.to_bytes(2, "big")
    result += random_nonce
    result += local_constant_id + b"\0\0" + local_variable_id.to_bytes(2, "big")
    result += b"\0\0" + bytes(32)
    result += host_constant_id + b"\0\0" + host_variable_id.to_bytes(2, "big")
    result += b"\x01\x01\0" + address + (12345).to_bytes(2, "big")
    result += player_id + len(encoded_name).to_bytes(4, "big") + b"\x01" + encoded_name
    return bytes(result)


def build_session_finalize(local_constant_id: bytes) -> bytes:
    if len(local_constant_id) != 6:
        raise ValueError("PIA constant ID must contain six bytes")
    return b"\x06" + local_constant_id + b"\0\0" + bytes(5) + b"\x01"


def respond_rtt(payload: bytes) -> bytes:
    if len(payload) < 16:
        raise MalformedDatagramError("truncated PIA RTT message")
    response = bytearray(payload[:21].ljust(21, b"\0"))
    response[0] = 1
    return bytes(response)


class PiaSession:
    """Host-acknowledged follower handshake; every ID is learned from incoming traffic."""

    def __init__(
        self,
        *,
        local_constant_id: bytes,
        local_ip: str,
        player_name: str,
        random_nonce: bytes,
        app_version: int,
        protocols: tuple[tuple[int, int], ...] = ((1, 0), (3, 5), (5, 1), (10, 3), (13, 7), (15, 0)),
        player_id: bytes = bytes.fromhex("00000000000000010000000000000000"),
    ) -> None:
        if len(local_constant_id) != 6:
            raise ValueError("local PIA constant ID must contain six bytes")
        self.local_constant_id = bytes(local_constant_id)
        self.local_ip = local_ip
        self.player_name = player_name
        self.random_nonce = bytes(random_nonce)
        self.app_version = app_version
        self.protocols = protocols
        self.player_id = bytes(player_id)
        self.phase = PiaSessionPhase.WAITING_FOR_NET
        self.local_variable_id: int | None = None
        self.host_variable_id: int | None = None
        self.host_constant_id: bytes | None = None
        self._finalize_sent = False

    def begin(self, host_constant_id: bytes, local_variable_id: int) -> PiaOutbound:
        """Create the follower's first v6 Session(join) request.

        The first packet deliberately addresses variable ID zero: the host has
        not yet advertised its ephemeral variable ID.  Its constant ID comes
        from the LDN participant record, while the local variable ID is a new
        non-zero value for this PIA session.
        """
        if len(host_constant_id) != 6:
            raise ValueError("host PIA constant ID must contain six bytes")
        if not 2 <= local_variable_id <= 0xFFFF:
            raise ValueError("local PIA variable ID must be a uint16 from 2 through 65535")
        if self.host_constant_id is not None and self.host_constant_id != host_constant_id:
            raise ProtocolStateError("PIA session was started for another host")
        if self.local_variable_id is not None and self.local_variable_id != local_variable_id:
            raise ProtocolStateError("PIA session local variable ID changed")
        self.host_constant_id = bytes(host_constant_id)
        self.local_variable_id = local_variable_id
        join = build_session_join(
            local_constant_id=self.local_constant_id,
            local_variable_id=local_variable_id,
            local_ip=self.local_ip,
            host_constant_id=self.host_constant_id,
            host_variable_id=0,
            player_name=self.player_name,
            random_nonce=self.random_nonce,
            app_version=self.app_version,
            protocols=self.protocols,
            player_id=self.player_id,
        )
        return self._outbound(
            PiaProtocol.SESSION,
            join,
            0,
            source=local_variable_id,
            compressed=True,
            establishing=True,
        )

    @property
    def connected(self) -> bool:
        return self.phase is PiaSessionPhase.CONNECTED

    def ingest(
        self,
        destination_variable_id: int,
        source_variable_id: int,
        message: PiaMessage,
    ) -> tuple[PiaOutbound, ...]:
        self._learn_header_ids(destination_variable_id, source_variable_id)
        if message.protocol is PiaProtocol.NET:
            return self._on_net(message.payload)
        if message.protocol is PiaProtocol.SESSION:
            return self._on_session(message.payload)
        if message.protocol in {PiaProtocol.RTT, PiaProtocol.RELIABLE}:
            if self.phase is PiaSessionPhase.WAITING_FOR_LIVE_TRAFFIC:
                self.phase = PiaSessionPhase.CONNECTED
            if message.protocol is PiaProtocol.RTT and self.phase is not PiaSessionPhase.WAITING_FOR_NET and message.payload[:1] == b"\0":
                return (self._outbound(PiaProtocol.RTT, respond_rtt(message.payload), 1, footer=self.host_variable_id),)
        return ()

    def _on_net(self, payload: bytes) -> tuple[PiaOutbound, ...]:
        _, message_type, body = parse_net(payload)
        if message_type == 0x11:
            host_variable_id, host_constant_id, sequence = parse_connection_request(payload)
            self.host_variable_id, self.host_constant_id = host_variable_id, host_constant_id
            if self.local_variable_id is None:
                raise ProtocolStateError("host Net request arrived before a local PIA variable ID")
            join = build_session_join(
                local_constant_id=self.local_constant_id,
                local_variable_id=self.local_variable_id,
                local_ip=self.local_ip,
                host_constant_id=host_constant_id,
                host_variable_id=host_variable_id,
                player_name=self.player_name,
                random_nonce=self.random_nonce,
                app_version=self.app_version,
                protocols=self.protocols,
                player_id=self.player_id,
            )
            return (
                self._outbound(PiaProtocol.NET, build_net_reply(0x12, sequence), 0, source=0, establishing=True),
                self._outbound(PiaProtocol.SESSION, join, 0, compressed=True, establishing=True),
            )
        if message_type == 0x50 and len(body) >= 4:
            return (self._outbound(PiaProtocol.NET, build_net_reply(0x51, int.from_bytes(body[:4], "big")), 0, establishing=True),)
        return ()

    def _on_session(self, payload: bytes) -> tuple[PiaOutbound, ...]:
        if not payload:
            raise MalformedDatagramError("empty PIA Session message")
        if payload[0] == 5 and not self._finalize_sent:
            if self.host_variable_id is None:
                raise ProtocolStateError("PIA Session update arrived without host identity")
            self._finalize_sent = True
            self.phase = PiaSessionPhase.WAITING_FOR_LIVE_TRAFFIC
            return (self._outbound(PiaProtocol.SESSION, build_session_finalize(self.local_constant_id), self.host_variable_id, footer=self.host_variable_id),)
        return ()

    def _outbound(
        self,
        protocol: PiaProtocol,
        payload: bytes,
        destination: int,
        *,
        source: int | None = None,
        footer: int | None = None,
        compressed: bool = False,
        establishing: bool = False,
    ) -> PiaOutbound:
        if self.local_variable_id is None and source is None:
            raise ProtocolStateError("PIA local variable ID has not been learned")
        source_variable_id = self.local_variable_id if source is None else source
        assert source_variable_id is not None
        return PiaOutbound(PiaMessage(protocol, payload), destination, source_variable_id, footer, compressed, establishing)

    def _learn_header_ids(self, destination: int, source: int) -> None:
        # Session-control traffic uses destination ID 1 while its encrypted
        # footer carries the actual recipient.  The follower owns its random
        # local ID from `begin`, so only learn a header destination before that
        # bootstrap has happened.
        if destination and self.local_variable_id is None:
            self.local_variable_id = destination
        if source:
            self.host_variable_id = source
