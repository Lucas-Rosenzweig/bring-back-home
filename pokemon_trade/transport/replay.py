"""Deterministic replay transport for synthetic, expurgated capture JSONL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import trio

from pokemon_trade.errors import MalformedDatagramError, ProtocolStateError
from pokemon_trade.transport.base import Datagram, SessionContext
from pokemon_trade.transport.capture import CAPTURE_SCHEMA_VERSION, decode_session


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    direction: str
    payload: bytes
    source: tuple[str, int]
    destination: tuple[str, int]
    at: float
    order: int


class ReplayTransport:
    """Replay a capture without sleeping and verify every emitted datagram."""

    def __init__(
        self,
        session: SessionContext,
        records: tuple[ReplayRecord, ...],
        *,
        max_clock_step_seconds: float = 1 / 120,
    ) -> None:
        if max_clock_step_seconds <= 0:
            raise ValueError("replay clock step must be positive")
        self.session = session
        self._records = records
        self._incoming = tuple(record for record in records if record.direction == "in")
        self._outgoing = tuple(record for record in records if record.direction == "out")
        self._incoming_index = 0
        self._outgoing_index = 0
        self._current_time = 0.0
        self._max_clock_step_seconds = max_clock_step_seconds
        self._outgoing_progress = trio.Event()
        self._closed = False

    @property
    def records(self) -> tuple[ReplayRecord, ...]:
        """Expose immutable wire records to game-specific replay setup."""
        return self._records

    def current_time(self) -> float:
        """Return capture-relative logical time for an injected game clock."""
        return self._current_time

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        max_clock_step_seconds: float = 1 / 120,
    ) -> ReplayTransport:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise MalformedDatagramError("empty replay capture")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise MalformedDatagramError("invalid replay capture header") from error
        if not isinstance(header, dict) or header.get("schema") != CAPTURE_SCHEMA_VERSION:
            raise MalformedDatagramError("unsupported replay capture schema")
        try:
            session = decode_session(header["session"])
        except (KeyError, ValueError) as error:
            raise MalformedDatagramError("invalid replay session") from error
        records: list[ReplayRecord] = []
        for line_number, line in enumerate(lines[1:], start=2):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError
                direction = value["direction"]
                source = tuple(value["source"])
                destination = tuple(value["destination"])
                if direction not in {"in", "out"} or len(source) != 2 or len(destination) != 2:
                    raise ValueError
                records.append(
                    ReplayRecord(
                        direction,
                        bytes.fromhex(value["payload"]),
                        (str(source[0]), int(source[1])),
                        (str(destination[0]), int(destination[1])),
                        float(value["at"]),
                        line_number - 2,
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise MalformedDatagramError(
                    f"invalid replay record at line {line_number}"
                ) from error
        return cls(
            session,
            tuple(records),
            max_clock_step_seconds=max_clock_step_seconds,
        )

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        self._ensure_open()
        if self._outgoing_index >= len(self._outgoing):
            raise ProtocolStateError("replay produced an unexpected extra output")
        record = self._outgoing[self._outgoing_index]
        if record.payload != payload or record.destination != destination:
            common = min(len(record.payload), len(payload))
            first_difference = next(
                (index for index in range(common) if record.payload[index] != payload[index]),
                common,
            )
            raise ProtocolStateError(
                f"replay output #{self._outgoing_index + 1} does not match the capture "
                f"(expected {len(record.payload)} bytes to {record.destination}, got "
                f"{len(payload)} bytes to {destination}; first difference at byte "
                f"{first_difference})"
            )
        self._outgoing_index += 1
        self._current_time = max(self._current_time, record.at)
        progress = self._outgoing_progress
        self._outgoing_progress = trio.Event()
        progress.set()

    async def receive(self) -> Datagram:
        self._ensure_open()
        if self._incoming_index >= len(self._incoming):
            raise ProtocolStateError("replay capture ended unexpectedly")
        record = self._incoming[self._incoming_index]
        while (
            self._outgoing_index < len(self._outgoing)
            and self._outgoing[self._outgoing_index].order < record.order
        ):
            # Preserve capture causality without busy-waiting. A sibling sender
            # wakes this event directly; when the expected output belongs to a
            # game tick, the caller's outer VBlank cancel scope interrupts the
            # wait and produces it before retrying receive.
            next_output = self._outgoing[self._outgoing_index]
            # Advance virtual time in bounded increments.  A long quiet
            # capture interval may contain thousands of game ticks which do
            # not emit datagrams (for example, FRLG's trade animation).  A
            # single jump would skip those internal state transitions.
            self._current_time = min(
                next_output.at,
                self._current_time + self._max_clock_step_seconds,
            )
            await self._outgoing_progress.wait()
        self._current_time = max(self._current_time, record.at)
        self._incoming_index += 1
        return Datagram(record.payload, record.source, record.destination, record.at)

    async def aclose(self) -> None:
        self._closed = True

    def assert_finished(self) -> None:
        if (
            self._incoming_index != len(self._incoming)
            or self._outgoing_index != len(self._outgoing)
        ):
            raise ProtocolStateError("replay did not consume every captured datagram")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("replay transport is closed")
