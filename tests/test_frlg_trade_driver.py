from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import trio

from pokemon_trade.api import TradeRequest
from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.driver import FrlgLiveWireConfig
from pokemon_trade.games.frlg.identity import FrlgIdentity, FrlgVariant, LinkPlayerRecord
from pokemon_trade.games.frlg.pokemon import Pk3
from pokemon_trade.games.frlg.gba.ni import NiState
from pokemon_trade.games.frlg.gba.blocks import BlockSender
from pokemon_trade.games.frlg.gba.link import RfuFollowerLink
from pokemon_trade.games.frlg.gba.rfu import RfuCommand, RfuSlot
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.session import PiaSession, PiaSessionPhase
from pokemon_trade.games.frlg.pia.wire import FrlgPiaWire
from pokemon_trade.games.frlg.trade.model import FrlgCommand, FrlgCommandKind, FrlgWireSignalKind
from pokemon_trade.games.frlg.trade.wire import (
    LINKCMD_BOTH_CANCEL_TRADE,
    LINKCMD_CONFIRM_FINISH_TRADE,
    LINKCMD_PARTNER_CANCEL_TRADE,
    LINKCMD_REQUEST_CANCEL,
    LINKCMD_SET_MONS_TO_TRADE,
    LINKCMD_START_TRADE,
    link_command,
)
from pokemon_trade.games.frlg.trade_driver import FrlgTradePiaRfuDriver, FrlgTradeWireConfig
from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext


def pokemon(value: int) -> Pk3:
    header = bytearray(32)
    header[:4] = value.to_bytes(4, "little")
    header[4:8] = (9).to_bytes(4, "little")
    return Pk3.from_decrypted(bytes(header), bytes([value]) * 48)


class EmptyTransport:
    session = SessionContext(
        bytes(range(16)),
        0x01006FA0233F8000,
        1,
        88,
        "fake0",
        ParticipantAddress("169.254.1.2", "02:00:00:00:00:02"),
        ParticipantAddress("169.254.1.1", "02:00:00:00:00:01"),
        "169.254.1.255",
    )

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        return None

    async def receive(self) -> Datagram:
        await trio.sleep_forever()
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        return None


class FrlgTradePiaRfuDriverTest(unittest.TestCase):
    def test_disconnect_after_trade_skips_cancel_handshake_and_exits(self) -> None:
        async def scenario() -> None:
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(),
                TradeRequest((pokemon(1).to_artifact(),)),
                FrlgTradeWireConfig(
                    FrlgLiveWireConfig(
                        bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                        random_nonce=bytes(4),
                    ),
                    record.block(),
                    bytes(100),
                    disconnect_after_trade=True,
                ),
            )
            await driver.start()

            disconnect = AsyncMock()
            with patch.object(driver, "_disconnect_now", new=disconnect):
                await driver.send(FrlgCommand(FrlgCommandKind.LEAVE))

            disconnect.assert_awaited_once_with()
            self.assertTrue(driver._leaving)
            self.assertIsNone(driver._block_sender)
            self.assertIsNone(driver._current_block)
            self.assertEqual(
                tuple(signal.kind for signal in driver._signals),
                (FrlgWireSignalKind.EXITED,),
            )

        trio.run(scenario)

    def test_animation_clock_advances_while_reliable_emission_is_blocked(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((pokemon(1).to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
                animation_frames=2,
            ),
        )
        driver._animation_remaining = 2

        driver._on_link_clock()
        driver._on_link_clock()
        driver._on_link_clock()

        self.assertIsNotNone(driver._block_sender)
        self.assertTrue(driver._ready_finish_sent)

    def test_start_trade_initiates_exactly_one_scene_seam_standby_four(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((pokemon(1).to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            ),
        )
        driver._barrier.next_standby_count = 4

        driver._consume_link_command(LINKCMD_START_TRADE, 0)
        driver._consume_link_command(LINKCMD_START_TRADE, 0)
        slot = driver._barrier.outgoing()

        self.assertIsNotNone(slot)
        assert slot is not None
        self.assertEqual(slot.command, RfuCommand.READY_EXIT_STANDBY)
        self.assertEqual(slot.words[1], 4)
        self.assertTrue(driver._scene_seam_waiting)

    def test_commit_initiates_save_barriers_until_the_host_restarts_party_exchange(self) -> None:
        offered, received = pokemon(1), pokemon(2)
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((offered.to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            ),
        )
        trio.run(driver.start)
        host_party = received.party_bytes + bytes(500)
        for offset in range(0, 600, 200):
            driver._host_party.add(host_party[offset : offset + 200])
        driver._offered_slot = 0
        driver._host_cursor = 0
        driver._barrier.next_standby_count = 5

        driver._commit()
        first = driver._barrier.outgoing()
        assert first is not None
        self.assertEqual(first.words[1], 5)
        driver._block_sender = None
        driver._serve_request(0)

        self.assertFalse(driver._save_chain_active)
        self.assertFalse(driver._barrier.active)

    def test_one_sided_cancel_reselects_cancel_after_sixty_vblanks(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((pokemon(1).to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            ),
        )
        driver._leaving = True

        driver._consume_link_command(LINKCMD_PARTNER_CANCEL_TRADE, 0)
        for _ in range(61):
            driver._on_link_clock()

        self.assertIsNotNone(driver._block_sender)
        self.assertEqual(driver._current_block, link_command(LINKCMD_REQUEST_CANCEL))

    def test_mutual_cancel_starts_two_exit_standbys_at_count_eleven(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((pokemon(1).to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            ),
        )
        driver._leaving = True
        driver._barrier.next_standby_count = 11

        driver._consume_link_command(LINKCMD_BOTH_CANCEL_TRADE, 0)
        first = driver._barrier.outgoing()
        assert first is not None
        self.assertEqual(first.words[1], 11)
        driver._on_rfu_slots(
            ((0, RfuSlot((RfuCommand.READY_EXIT_STANDBY, 11, 0, 0, 0, 0, 0))),)
        )

        self.assertEqual(driver._cancel_exit_rounds_remaining, 1)
        self.assertEqual(driver._barrier.next_standby_count, 12)

    def test_full_reliable_window_pauses_block_sender_instead_of_bursting(self) -> None:
        async def scenario() -> None:
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            config = FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            )
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(), TradeRequest((pokemon(1).to_artifact(),)), config
            )
            await driver.start()
            link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(26))
            link._accepted = True  # type: ignore[attr-defined]
            link._host_uni_seen = True  # type: ignore[attr-defined]
            link._ni.state = NiState.DONE
            driver._link_started = True
            driver._wire = FrlgPiaWire(
                PiaPeer(
                    PiaSession(
                        local_constant_id=b"LOCAL!", local_ip="169.254.1.2",
                        player_name="EMU", random_nonce=bytes(4), app_version=88,
                    ),
                    ssid=bytes(range(16)), game_key=bytes(range(16)),
                    local_ip="169.254.1.2",
                )
            )
            driver._wire.peer.session.local_variable_id = 1
            driver._wire.peer.session.host_variable_id = 2
            driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED
            for _ in range(6):
                driver._wire.queue_frame(b"WG\0\0")
            driver._wire.drain_datagrams()
            driver._block_sender = BlockSender(record.block())
            driver._slot_credit = 2

            driver._link_tick()
            self.assertEqual(driver._block_sender._init_emits, 0)

            driver._wire._apply_acknowledgement(
                b"\0\x01" + (0xFFF1).to_bytes(2, "big") + bytes(16)
            )
            driver._link_tick()
            self.assertEqual(driver._block_sender._init_emits, 1)

        trio.run(scenario)

    def test_room_entry_requires_game_layer_held_keys(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        config = FrlgTradeWireConfig(
            FrlgLiveWireConfig(
                bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                random_nonce=bytes(4),
            ),
            record.block(),
            bytes(100),
        )
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(), TradeRequest((pokemon(1).to_artifact(),)), config
        )
        held_keys = RfuSlot((RfuCommand.SEND_HELD_KEYS, 0x0111, 0, 0, 0, 0, 0))

        driver._on_rfu_slots(((0, held_keys),))
        driver._on_rfu_slots(((0, held_keys),))

        self.assertTrue(driver._host_in_seat)
        self.assertEqual(
            tuple(signal.kind for signal in driver._signals),
            (FrlgWireSignalKind.ROOM_ENTERED,),
        )

    def test_rejects_a_host_that_assigns_the_follower_to_another_seat(self) -> None:
        record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
        driver = FrlgTradePiaRfuDriver(
            EmptyTransport(),
            TradeRequest((pokemon(1).to_artifact(),)),
            FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            ),
        )

        with self.assertRaises(ProtocolStateError):
            driver._on_rfu_slots(
                ((0, RfuSlot((RfuCommand.SEND_PLAYER_IDS, 2, 0, 0, 0, 0, 0))),)
            )

    def test_seat_keepalive_uses_rolling_count_and_one_ready_key(self) -> None:
        async def scenario() -> None:
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            config = FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26), random_nonce=bytes(4)
                ),
                record.block(),
                bytes(100),
            )
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(), TradeRequest((pokemon(1).to_artifact(),)), config
            )
            await driver.start()
            link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(26))
            link._accepted = True  # type: ignore[attr-defined]
            link._host_uni_seen = True  # type: ignore[attr-defined]
            link._ni.state = NiState.DONE
            driver._wire = FrlgPiaWire(
                PiaPeer(
                    PiaSession(local_constant_id=b"LOCAL!", local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88),
                    ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2",
                )
            )
            driver._wire.peer.session.local_variable_id = 1
            driver._wire.peer.session.host_variable_id = 2
            driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED
            driver._plan.block_for_request(0)
            driver._host_in_seat = True
            driver._host_ready = True

            self.assertTrue(driver._on_vblank())
            sent = next(iter(driver._wire._unacknowledged.values()))[0].payload
            first = RfuSlot.parse(sent[14:28])
            self.assertEqual(first.words[1], 0x0116)
            self.assertTrue(driver._self_ready_sent)

        trio.run(scenario)

    def test_entry_barrier_waits_for_both_link_player_blocks(self) -> None:
        async def scenario() -> None:
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            config = FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26), random_nonce=bytes(4)
                ),
                record.block(),
                bytes(100),
            )
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(), TradeRequest((pokemon(1).to_artifact(),)), config
            )
            await driver.start()

            driver._sending_entry_link = True
            driver._start_block(record.block().ljust(200, b"\0"))
            assert driver._block_sender is not None
            while driver._block_sender.next_slot() is not None:
                pass
            driver._begin_link_player_barrier_when_established()
            self.assertFalse(driver._barrier.active)
            self.assertFalse(driver._entry_barrier_waiting)

            driver._consume_host_block(17, record.block())
            self.assertFalse(driver._barrier.active)

            echoed = BlockSender(record.block().ljust(200, b"\0"))
            while (slot := echoed.next_slot()) is not None:
                driver._on_rfu_slots(((1, slot),))
            self.assertTrue(driver._barrier.active)
            self.assertTrue(driver._entry_barrier_waiting)

        trio.run(scenario)

    def test_entry_barrier_retires_obsolete_idle_backlog(self) -> None:
        async def scenario() -> None:
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            config = FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26),
                    random_nonce=bytes(4),
                ),
                record.block(),
                bytes(100),
            )
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(), TradeRequest((pokemon(1).to_artifact(),)), config
            )
            await driver.start()
            link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(26))
            link._accepted = True  # type: ignore[attr-defined]
            link._host_uni_seen = True  # type: ignore[attr-defined]
            link._ni.state = NiState.DONE
            driver._wire = FrlgPiaWire(
                PiaPeer(
                    PiaSession(
                        local_constant_id=b"LOCAL!", local_ip="169.254.1.2",
                        player_name="EMU", random_nonce=bytes(4), app_version=88,
                    ),
                    ssid=bytes(range(16)), game_key=bytes(range(16)),
                    local_ip="169.254.1.2",
                )
            )
            driver._wire.peer.session.local_variable_id = 1
            driver._wire.peer.session.host_variable_id = 2
            driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED
            for _ in range(12):
                link.queue_uni(RfuSlot.idle())
                driver._flush_link_frames()
            driver._wire.drain_datagrams()

            driver._local_link_player_complete = True
            driver._host_link_player_complete = True
            driver._begin_link_player_barrier_when_established()
            self.assertTrue(driver._on_vblank())

            self.assertEqual(len(driver._wire._unacknowledged), 6)
            self.assertEqual(len(driver._wire._pending_data), 1)
            next_expected = (max(driver._wire._unacknowledged) + 1).to_bytes(2, "big")
            driver._wire._apply_acknowledgement(b"\0\x01" + next_expected + bytes(16))
            driver._wire.poll_retransmissions()

            queued = tuple(
                reliable.payload
                for reliable, _, _ in driver._wire._unacknowledged.values()
            )
            self.assertEqual(len(queued), 1)
            self.assertEqual(
                RfuSlot.parse(queued[0][14:28]).command,
                RfuSlot((0x6600, 0, 0, 0, 0, 0, 0)).command,
            )

        trio.run(scenario)

    def test_commits_only_after_leader_confirmation_with_selected_host_party_entry(self) -> None:
        async def scenario() -> None:
            offered, received = pokemon(1), pokemon(2)
            record = LinkPlayerRecord(FrlgIdentity(1, 2, "EMU", FrlgVariant.FIRERED))
            wire_config = FrlgTradeWireConfig(
                FrlgLiveWireConfig(
                    bytes(range(16)), b"LOCAL!", "EMU", b"\x12\x34", bytes(26), random_nonce=bytes(4)
                ),
                record.block(),
                bytes(100),
                animation_frames=0,
            )
            driver = FrlgTradePiaRfuDriver(
                EmptyTransport(), TradeRequest((offered.to_artifact(),)), wire_config
            )
            await driver.start()

            host_party = received.party_bytes + bytes(500)
            for offset in range(0, 600, 200):
                driver._consume_host_block(17, host_party[offset : offset + 200])
            driver._consume_host_block(4, bytes(40))
            self.assertFalse(driver._signals)
            driver._local_ribbons_complete = True
            driver._maybe_announce_menu()
            self.assertEqual(driver._signals.popleft().kind, FrlgWireSignalKind.MENU_READY)

            await driver.send(FrlgCommand(FrlgCommandKind.OFFER_SLOT, 0))
            driver._block_sender = None  # model completion of follower READY_TO_TRADE
            driver._consume_host_block(2, link_command(LINKCMD_SET_MONS_TO_TRADE, 0))
            driver._block_sender = None  # model completion of follower INIT_BLOCK
            driver._consume_host_block(2, link_command(LINKCMD_START_TRADE))
            driver._on_link_clock()
            driver._block_sender = None  # model completion of follower READY_FINISH
            driver._consume_host_block(2, link_command(LINKCMD_CONFIRM_FINISH_TRADE))

            signal = driver._signals.popleft()
            self.assertEqual(signal.kind, FrlgWireSignalKind.TRADE_COMMITTED)
            self.assertEqual(signal.received_pk3, received.party_bytes)

        trio.run(scenario)
