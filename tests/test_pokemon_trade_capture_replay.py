from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import trio

from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext
from pokemon_trade.transport.capture import CaptureTransport
from pokemon_trade.transport.replay import ReplayTransport


class MemoryTransport:
    def __init__(self, session: SessionContext, incoming: Datagram) -> None:
        self.session = session
        self._incoming = incoming
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        self.sent.append((payload, destination))

    async def receive(self) -> Datagram:
        return self._incoming

    async def aclose(self) -> None:
        return None


def session() -> SessionContext:
    return SessionContext(
        bytes(range(16)),
        42,
        7,
        1,
        "ldnclient",
        ParticipantAddress("169.254.1.2", "02:00:00:00:00:02"),
        ParticipantAddress("169.254.1.1", "02:00:00:00:00:01"),
        "169.254.1.255",
    )


class CaptureReplayTest(unittest.TestCase):
    def test_capture_replays_exact_bidirectional_sequence(self) -> None:
        async def scenario(path: Path) -> None:
            context = session()
            inner = MemoryTransport(
                context,
                Datagram(b"reply", ("169.254.1.1", 12345), ("169.254.1.2", 12345), 1.0),
            )
            capture = CaptureTransport.to_path(inner, path)
            await capture.send(b"request", ("169.254.1.1", 12345))
            self.assertEqual((await capture.receive()).payload, b"reply")
            await capture.aclose()

            replay = ReplayTransport.from_path(path)
            await replay.send(b"request", ("169.254.1.1", 12345))
            self.assertEqual((await replay.receive()).payload, b"reply")
            replay.assert_finished()

        with tempfile.TemporaryDirectory() as directory:
            trio.run(scenario, Path(directory) / "capture.jsonl")

    def test_replay_waits_for_a_causally_earlier_output_without_deadlocking(self) -> None:
        async def scenario(path: Path) -> None:
            context = session()
            inner = MemoryTransport(
                context,
                Datagram(b"reply", ("169.254.1.1", 12345), ("169.254.1.2", 12345), 1.0),
            )
            capture = CaptureTransport.to_path(inner, path)
            await capture.send(b"request", ("169.254.1.1", 12345))
            await capture.receive()
            await capture.aclose()

            replay = ReplayTransport.from_path(path)
            received: list[bytes] = []

            async def receive_reply() -> None:
                received.append((await replay.receive()).payload)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(receive_reply)
                await trio.lowlevel.checkpoint()
                self.assertEqual(received, [])
                await replay.send(b"request", ("169.254.1.1", 12345))
            self.assertEqual(received, [b"reply"])
            replay.assert_finished()

        with tempfile.TemporaryDirectory() as directory:
            trio.run(scenario, Path(directory) / "paced.jsonl")
