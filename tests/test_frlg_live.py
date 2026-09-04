from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import trio

from pokemon_trade.api import TradeRequest
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant
from pokemon_trade.api import TradeResult, TradeStatus
from pokemon_trade.errors import PeerDisconnectedError
from pokemon_trade.games.frlg.live import build_trade_wire_config, run_connected_trade
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.transport.base import ParticipantAddress, SessionContext


def pokemon() -> Pk3:
    header = bytearray(32)
    header[4:8] = (3).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes(48))


class FrlgLiveCompositionTest(unittest.TestCase):
    def test_derives_ephemeral_wire_config_without_console_secrets(self) -> None:
        session = SessionContext(
            bytes(16), 0x01006FA0233F8000, 1, 88, "fake0",
            ParticipantAddress("169.254.1.2", "02:00:00:00:00:02"),
            ParticipantAddress("169.254.1.1", "02:00:00:00:00:01"), "169.254.1.255",
        )
        identity = FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED)
        with patch("pokemon_trade.games.frlg.live.secrets.token_bytes", return_value=b"\x12\x34"):
            config = build_trade_wire_config(
                session,
                TradeRequest((pokemon().to_artifact(),)),
                identity,
                disconnect_after_trade=True,
            )

        self.assertEqual(config.link.pia_constant_id, bytes.fromhex("020000000002"))
        self.assertEqual(config.link.rfu_connect_id, b"\x12\x34")
        self.assertEqual(len(config.link.rfu_game_data), 26)
        self.assertEqual(len(config.link_player_block), 60)
        self.assertTrue(config.disconnect_after_trade)

    def test_connection_monitor_failure_becomes_typed_peer_disconnect(self) -> None:
        class FakeConnection:
            async def monitor(self) -> None:
                raise ConnectionError("station lost")

        class FakeTransport:
            session = SessionContext(
                bytes(16), 0x01006FA0233F8000, 1, 88, "fake0",
                ParticipantAddress("169.254.1.2", "02:00:00:00:00:02"),
                ParticipantAddress("169.254.1.1", "02:00:00:00:00:01"),
                "169.254.1.255",
            )

            def __init__(self) -> None:
                self.closed = False

            async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
                return None

            async def receive(self):
                await trio.sleep_forever()

            async def aclose(self) -> None:
                self.closed = True

        async def never_finishes(*args, **kwargs):
            await trio.sleep_forever()
            return TradeResult(TradeStatus.FAILED, (), ())

        async def scenario() -> None:
            transport = FakeTransport()
            request = TradeRequest((pokemon().to_artifact(),))
            identity = FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED)
            with (
                patch(
                    "pokemon_trade.games.frlg.live.LdnUdpTransport.open",
                    new=AsyncMock(return_value=transport),
                ),
                patch("pokemon_trade.games.frlg.live.run_trade", new=never_finishes),
            ):
                with self.assertRaises(PeerDisconnectedError):
                    await run_connected_trade(
                        FakeConnection(), "fake0", request, identity, lambda event: None
                    )
            self.assertTrue(transport.closed)

        trio.run(scenario)
