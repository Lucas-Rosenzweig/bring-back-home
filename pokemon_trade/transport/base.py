"""The intentionally small transport contract exposed to game plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ParticipantAddress:
    ip_address: str
    mac_address: str


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Immutable LDN session facts copied after association has completed."""

    ssid: bytes
    communication_id: int
    scene_id: int
    app_version: int
    interface: str
    local: ParticipantAddress
    host: ParticipantAddress
    broadcast_address: str

    def __post_init__(self) -> None:
        if len(self.ssid) != 16:
            raise ValueError("LDN session SSID must contain 16 bytes")
        if not self.interface:
            raise ValueError("LDN session interface must be non-empty")


@dataclass(frozen=True, slots=True)
class Datagram:
    payload: bytes
    source: tuple[str, int]
    destination: tuple[str, int]
    received_at: float

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("empty UDP datagrams are not valid trade payloads")
        if not 1 <= self.source[1] <= 65535 or not 1 <= self.destination[1] <= 65535:
            raise ValueError("UDP ports must be between 1 and 65535")
        object.__setattr__(self, "payload", bytes(self.payload))


class DatagramTransport(Protocol):
    session: SessionContext

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None: ...

    async def receive(self) -> Datagram: ...

    async def aclose(self) -> None: ...
