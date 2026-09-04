from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import trio
from trio.testing import MockClock

from pokemon_trade.api import TradeEvent, TradeEventKind, TradeRequest, TradeStatus
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant
from pokemon_trade.games.frlg.driver import FRLG_VBLANK_SECONDS
from pokemon_trade.games.frlg.live import FRLG_PIA_GAME_KEY, frlg_live_registry
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.games.frlg.replay import FrlgReplayEntropy, extract_frlg_replay_entropy
from pokemon_trade.service import run_trade
from pokemon_trade.transport.capture import CaptureTransport
from pokemon_trade.transport.replay import ReplayTransport
from tests.fakes.frlg_host import LOCAL_VARIABLE_ID, SyntheticFrlgHostTransport

FIXTURE = Path(__file__).parent / "fixtures" / "frlg" / "synthetic-trade-v1.jsonl"


def pokemon(value: int) -> Pk3:
    header = bytearray(32)
    header[:4] = value.to_bytes(4, "little")
    header[4:8] = (7).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes([value]) * 48)


class FrlgFullStackReplayTest(unittest.TestCase):
    def test_synthetic_host_capture_replays_the_complete_trade_path(self) -> None:
        async def scenario(path: Path) -> None:
            offered, received = pokemon(1), pokemon(2)
            request = TradeRequest((offered.to_artifact(),))
            identity = FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED)
            entropy = FrlgReplayEntropy(
                LOCAL_VARIABLE_ID,
                bytes.fromhex("10203040"),
                bytes.fromhex("1234"),
                tuple(value.to_bytes(8, "big") for value in range(1, 5000)),
            )
            events: list[TradeEvent] = []
            host = SyntheticFrlgHostTransport(received)
            capture = CaptureTransport.to_path(host, path, clock=trio.current_time)
            result = await run_trade(
                frlg_live_registry(
                    identity,
                    replay_entropy=entropy,
                    clock=trio.current_time,
                    animation_frames=2,
                ),
                capture,
                request,
                events.append,
            )
            await capture.aclose()

            self.assertEqual(path.read_bytes(), FIXTURE.read_bytes())

            self.assertEqual(result.status, TradeStatus.COMPLETED)
            self.assertEqual(result.received[0].data, received.decrypted_pk3_bytes())
            expected_events = [
                TradeEventKind.LDN_READY,
                TradeEventKind.PEER_CONNECTED,
                TradeEventKind.ROOM_ENTERED,
                TradeEventKind.MENU_READY,
                TradeEventKind.OFFERED,
                TradeEventKind.COMMITTED,
                TradeEventKind.SAVING,
                TradeEventKind.LEAVING,
                TradeEventKind.COMPLETED,
            ]
            self.assertEqual([event.kind for event in events], expected_events)

            replay = ReplayTransport.from_path(
                path,
                max_clock_step_seconds=FRLG_VBLANK_SECONDS,
            )
            replay_events: list[TradeEvent] = []
            replay_result = await run_trade(
                frlg_live_registry(
                    identity,
                    replay_entropy=extract_frlg_replay_entropy(replay, FRLG_PIA_GAME_KEY),
                    clock=replay.current_time,
                    animation_frames=2,
                ),
                replay,
                request,
                replay_events.append,
            )
            replay.assert_finished()
            await replay.aclose()

            self.assertEqual(replay_result, result)
            self.assertEqual([event.kind for event in replay_events], expected_events)

        with tempfile.TemporaryDirectory() as directory:
            trio.run(
                scenario,
                Path(directory) / "synthetic-frlg.jsonl",
                clock=MockClock(autojump_threshold=0),
            )
