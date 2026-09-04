"""Versioned JSONL datagram capture decorator, independent of any game."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from pokemon_trade.transport.base import Datagram, DatagramTransport, ParticipantAddress, SessionContext

CAPTURE_SCHEMA_VERSION = 1


def _encode_session(session: SessionContext) -> dict[str, object]:
    return {
        "ssid": session.ssid.hex(),
        "communication_id": session.communication_id,
        "scene_id": session.scene_id,
        "app_version": session.app_version,
        "interface": session.interface,
        "local": {"ip_address": session.local.ip_address, "mac_address": session.local.mac_address},
        "host": {"ip_address": session.host.ip_address, "mac_address": session.host.mac_address},
        "broadcast_address": session.broadcast_address,
    }


def decode_session(value: object) -> SessionContext:
    if not isinstance(value, dict):
        raise ValueError("capture session must be an object")
    local = value.get("local")
    host = value.get("host")
    if not isinstance(local, dict) or not isinstance(host, dict):
        raise ValueError("capture session participants are missing")
    try:
        return SessionContext(
            ssid=bytes.fromhex(str(value["ssid"])),
            communication_id=int(value["communication_id"]),
            scene_id=int(value["scene_id"]),
            app_version=int(value["app_version"]),
            interface=str(value["interface"]),
            local=ParticipantAddress(str(local["ip_address"]), str(local["mac_address"])),
            host=ParticipantAddress(str(host["ip_address"]), str(host["mac_address"])),
            broadcast_address=str(value["broadcast_address"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid capture session") from error


class CaptureTransport:
    """Persist the exact datagram sequence of a wrapped transport.

    Live capture files are sensitive and callers must keep them local.  The
    constructor creates paths mode 0600 and never attempts anonymisation.
    """

    def __init__(
        self,
        inner: DatagramTransport,
        stream: TextIO,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = inner.session
        self._inner = inner
        self._stream = stream
        self._clock = clock
        self._started_at = clock()
        self._write({"schema": CAPTURE_SCHEMA_VERSION, "session": _encode_session(self.session)})

    @classmethod
    def to_path(
        cls,
        inner: DatagramTransport,
        path: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> CaptureTransport:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return cls(inner, os.fdopen(descriptor, "w", encoding="utf-8"), clock=clock)

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        await self._inner.send(payload, destination)
        self._record("out", payload, (self.session.local.ip_address, destination[1]), destination)

    async def receive(self) -> Datagram:
        datagram = await self._inner.receive()
        self._record("in", datagram.payload, datagram.source, datagram.destination)
        return datagram

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            self._stream.close()

    def _record(
        self,
        direction: str,
        payload: bytes,
        source: tuple[str, int],
        destination: tuple[str, int],
    ) -> None:
        self._write(
            {
                "at": self._clock() - self._started_at,
                "direction": direction,
                "payload": payload.hex(),
                "source": list(source),
                "destination": list(destination),
            }
        )

    def _write(self, record: dict[str, object]) -> None:
        self._stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        self._stream.flush()
