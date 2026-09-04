"""Follower-only FRLG trade adapter from RFU blocks to semantic trade signals."""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.api import TradeRequest
from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.driver import FrlgLiveWireConfig, FrlgPiaRfuDriver
from pokemon_trade.games.frlg.gba.barriers import BarrierKind, BarrierResponder
from pokemon_trade.games.frlg.gba.blocks import FRAGMENT_SIZE, BlockReceiver, BlockSender
from pokemon_trade.games.frlg.gba.rfu import RfuCommand, RfuSlot
from pokemon_trade.games.frlg.pokemon import FrlgTeam
from pokemon_trade.games.frlg.trade.model import (
    FrlgCommand,
    FrlgCommandKind,
    FrlgWireSignal,
    FrlgWireSignalKind,
)
from pokemon_trade.games.frlg.trade.wire import (
    BLOCK_REQUEST_200,
    BLOCK_REQUEST_RIBBONS,
    BLOCK_REQUEST_TRAINER_CARD,
    FrlgFollowerBlockPlan,
    FrlgPartyBuffer,
    LINKCMD_BOTH_CANCEL_TRADE,
    LINKCMD_CONFIRM_FINISH_TRADE,
    LINKCMD_INIT_BLOCK,
    LINKCMD_PARTNER_CANCEL_TRADE,
    LINKCMD_PLAYER_CANCEL_TRADE,
    LINKCMD_READY_FINISH_TRADE,
    LINKCMD_READY_TO_TRADE,
    LINKCMD_REQUEST_CANCEL,
    LINKCMD_SET_MONS_TO_TRADE,
    LINKCMD_START_TRADE,
    is_link_player_block,
    link_command,
    parse_link_command,
)
from pokemon_trade.transport.base import DatagramTransport

LIVE_BARRIER_MAX_EMITS = 6
POST_SEAT_STANDBY_DELAY = 20
POST_SEAT_STANDBY_REARM_FRAMES = 60
CANCEL_RESELECT_DELAY = 60


@dataclass(frozen=True, slots=True)
class FrlgTradeWireConfig:
    """Local blocks needed by the FRLG follower trade-room protocol."""

    link: FrlgLiveWireConfig
    link_player_block: bytes
    trainer_card: bytes
    animation_frames: int = 1935
    disconnect_after_trade: bool = False

    def __post_init__(self) -> None:
        if len(self.link_player_block) != 60 or not is_link_player_block(self.link_player_block):
            raise ValueError("FRLG trade driver requires a valid 60-byte LinkPlayer block")
        if len(self.trainer_card) != 100:
            raise ValueError("FRLG trade driver requires a 100-byte trainer card")
        if self.animation_frames < 0:
            raise ValueError("FRLG animation frame count cannot be negative")
        object.__setattr__(self, "link_player_block", bytes(self.link_player_block))
        object.__setattr__(self, "trainer_card", bytes(self.trainer_card))


class FrlgTradePiaRfuDriver(FrlgPiaRfuDriver):
    """Map evidence-backed FRLG leader blocks into the public trade protocol."""

    def __init__(
        self,
        transport: DatagramTransport,
        request: TradeRequest,
        config: FrlgTradeWireConfig,
    ) -> None:
        super().__init__(transport, config.link)
        self._trade_config = config
        self._plan = FrlgFollowerBlockPlan(
            FrlgTeam.from_artifacts(request.team),
            link_player_block=config.link_player_block,
            trainer_card=config.trainer_card,
        )
        self._host_blocks = BlockReceiver(peer_count=1)
        # The leader rebroadcasts the follower's RFU slot at peer index 1.
        # Completion of that echoed block, rather than completion of our local
        # sender, proves the leader has installed the next game callback.
        self._echoed_child_blocks = BlockReceiver(peer_count=2)
        self._host_block_count: int | None = None
        self._host_party = FrlgPartyBuffer()
        self._block_sender: BlockSender | None = None
        self._current_block: bytes | None = None
        self._echoed_last_fragment = False
        self._echo_retry_cursor = 0
        self._offered_slot: int | None = None
        self._host_cursor: int | None = None
        self._animation_remaining: int | None = None
        self._ready_finish_sent = False
        self._pending_confirm = False
        self._awaiting_save = False
        self._leaving = False
        self._menu_announced = False
        self._host_ribbons_received = False
        self._local_ribbons_complete = False
        # The host repeats a barrier while it waits, but flooding a fresh
        # 0x6600/0x5f00 every VBlank keeps its receive queue permanently full.
        # Let Reliable retransmit the bounded slot instead.
        self._barrier = BarrierResponder(max_emits=LIVE_BARRIER_MAX_EMITS)
        self._sending_entry_link = False
        self._sending_trainer_card = False
        self._sending_menu_ribbons = False
        self._local_link_player_complete = False
        self._host_link_player_complete = False
        self._host_in_seat = False
        self._room_announced = False
        self._host_ready = False
        self._self_ready_sent = False
        self._held_key_count = 0
        self._post_seat_delay = 0
        self._post_seat_barriers_remaining = 0
        self._post_seat_barrier_quiet = 0
        self._entry_barrier_waiting = False
        self._seat_phase_over = False
        self._player_ids_seen = False
        self._scene_seam_started = False
        self._scene_seam_waiting = False
        self._scene_seam_quiet = 0
        self._save_chain_active = False
        self._save_barrier_quiet = 0
        self._cancel_retry_remaining: int | None = None
        self._cancel_exit_rounds_remaining = 0
        self._cancel_barrier_quiet = 0
        self._waiting_for_close = False
        self._host_exit_room = False

    async def send(self, command: FrlgCommand) -> None:
        self._ensure_started()
        if command.kind is FrlgCommandKind.OFFER_SLOT:
            if self._offered_slot is not None:
                raise ProtocolStateError("FRLG follower already offered a Pokémon this round")
            assert command.slot is not None
            self._offered_slot = command.slot
            self._start_block(link_command(LINKCMD_READY_TO_TRADE, command.slot))
            return
        if command.kind is FrlgCommandKind.SAVE:
            self._awaiting_save = True
            return
        if command.kind is FrlgCommandKind.LEAVE:
            self._leaving = True
            if self._trade_config.disconnect_after_trade:
                await self._disconnect_now()
                self._signals.append(FrlgWireSignal(FrlgWireSignalKind.EXITED))
                return
            self._start_block(link_command(LINKCMD_REQUEST_CANCEL))
            return
        raise AssertionError("unreachable FRLG command")

    def _on_rfu_slots(self, slots: tuple[tuple[int, RfuSlot], ...]) -> None:
        for peer_index, slot in slots:
            if peer_index == 1:
                completed = self._echoed_child_blocks.receive(peer_index, slot)
                if (
                    self._block_sender is not None
                    and slot.command is RfuCommand.SEND_BLOCK
                    and slot.fragment_index == self._block_sender.count - 1
                ):
                    self._echoed_last_fragment = True
                if completed is not None and self._block_sender is not None:
                    assert self._current_block is not None
                    if completed[: len(self._current_block)] != self._current_block:
                        raise ProtocolStateError("FRLG leader reflected a different child block")
                    self._finish_reflected_block()
                continue
            if peer_index != 0:
                continue
            if slot.command is RfuCommand.SEND_PLAYER_IDS:
                if not self._player_ids_seen:
                    self._player_ids_seen = True
                    if slot.words[1] != 2 or slot.words[2] != 1:
                        raise ProtocolStateError(
                            "FRLG host did not assign the follower to the expected right-hand seat"
                        )
                continue
            if slot.command is RfuCommand.SEND_BLOCK_REQUEST:
                self._serve_request(slot.request_type)
                continue
            if slot.command in {RfuCommand.READY_EXIT_STANDBY, RfuCommand.READY_CLOSE_LINK}:
                post_seat_barrier = self._post_seat_barriers_remaining > 0 and self._barrier.initiated
                scene_seam_barrier = self._scene_seam_waiting and self._barrier.initiated
                save_barrier = self._save_chain_active and self._barrier.initiated
                cancel_barrier = (
                    self._cancel_exit_rounds_remaining > 0 and self._barrier.initiated
                )
                if self._barrier.observe(slot):
                    self._entry_barrier_waiting = False
                    if post_seat_barrier:
                        self._post_seat_barriers_remaining -= 1
                        self._post_seat_barrier_quiet = 0
                    if scene_seam_barrier:
                        self._scene_seam_waiting = False
                        self._scene_seam_quiet = 0
                    if save_barrier:
                        self._save_barrier_quiet = 0
                    if cancel_barrier:
                        self._cancel_exit_rounds_remaining -= 1
                        self._cancel_barrier_quiet = 0
                        if self._cancel_exit_rounds_remaining == 0:
                            self._waiting_for_close = True
                continue
            if slot.command is RfuCommand.SEND_HELD_KEYS:
                self._host_in_seat = True
                self._entry_barrier_waiting = False
                if not self._room_announced:
                    # The held-key stream starts only once the leader is in
                    # the trade-room seat.  Unlike the first low-level UNI,
                    # this is game-layer evidence that entry actually
                    # completed and matches what is visible on the console.
                    self._room_announced = True
                    self._signals.append(FrlgWireSignal(FrlgWireSignalKind.ROOM_ENTERED))
                if slot.words[1] & 0xFF == 0x16:
                    self._host_ready = True
                if self._waiting_for_close and slot.words[1] & 0xFF == 0x17:
                    self._host_exit_room = True
                # A held-key stream marks the end of an entry barrier.  The
                # next phase owns the UNI slot, so stop mirroring the old one.
                if self._barrier.active and not self._barrier.initiated:
                    self._barrier = BarrierResponder(
                        self._barrier.next_standby_count,
                        max_emits=LIVE_BARRIER_MAX_EMITS,
                    )
                continue
            if slot.command is RfuCommand.SEND_BLOCK_INIT:
                self._host_block_count = slot.words[1]
            completed = self._host_blocks.receive(0, slot)
            if completed is not None:
                if self._host_block_count is None:
                    raise ProtocolStateError("FRLG host block completed without an init")
                self._consume_host_block(self._host_block_count, completed)
                self._host_block_count = None

    def _on_vblank(self) -> bool:
        if self._block_sender is not None:
            slot = self._block_sender.next_slot()
            if slot is not None:
                assert self._link is not None
                self._link.queue_uni(slot)
                self._flush_link_frames()
                return True
            # All fragments have entered Reliable, but the ROM sender remains
            # in SendLastBlock until the leader rebroadcasts a complete peer-1
            # assembly.  Network ACKs alone do not prove RFU consumption.
            missing = self._echoed_child_blocks.missing(1, self._block_sender.count)
            if missing:
                if self._echoed_last_fragment:
                    index = missing[self._echo_retry_cursor % len(missing)]
                    self._echo_retry_cursor += 1
                else:
                    index = self._block_sender.count - 1
                assert self._current_block is not None and self._link is not None
                start = index * FRAGMENT_SIZE
                self._link.queue_uni(
                    RfuSlot.block_fragment(
                        index,
                        self._current_block[start : start + FRAGMENT_SIZE],
                    )
                )
                self._flush_link_frames()
                return True
            return False
        if (
            (self._save_chain_active or self._cancel_exit_rounds_remaining > 0)
            and not self._barrier.active
        ):
            # CB2_SaveAndEndTrade reaches a sequence of child-side
            # SetLinkStandbyCallback calls.  Start the next count as soon as
            # the host has echoed the previous one; its save writes provide
            # the natural inter-round pacing.
            self._barrier.begin(BarrierKind.STANDBY)
        barrier_slot = self._barrier.outgoing()
        if (
            barrier_slot is None
            and self._barrier.active
            and self._barrier.initiated
            and (
                self._post_seat_barriers_remaining
                or self._scene_seam_waiting
                or self._save_chain_active
                or self._cancel_exit_rounds_remaining > 0
            )
        ):
            quiet_attr = (
                "_post_seat_barrier_quiet"
                if self._post_seat_barriers_remaining
                else (
                    "_scene_seam_quiet"
                    if self._scene_seam_waiting
                    else (
                        "_save_barrier_quiet"
                        if self._save_chain_active
                        else "_cancel_barrier_quiet"
                    )
                )
            )
            quiet = getattr(self, quiet_attr) + 1
            setattr(self, quiet_attr, quiet)
            if quiet >= POST_SEAT_STANDBY_REARM_FRAMES:
                self._barrier.rearm()
                setattr(self, quiet_attr, 0)
                barrier_slot = self._barrier.outgoing()
        if (
            barrier_slot is None
            and self._host_in_seat
            and self._self_ready_sent
            and self._post_seat_barriers_remaining
        ):
            if self._post_seat_delay:
                self._post_seat_delay -= 1
            elif not self._barrier.active:
                self._barrier.begin(BarrierKind.STANDBY)
                self._begin_entry_barrier_wait()
                barrier_slot = self._barrier.outgoing()
        if barrier_slot is not None:
            assert self._link is not None
            self._link.queue_uni(barrier_slot)
            self._flush_link_frames()
            return True
        if (
            self._host_in_seat
            and self._plan.link_player_sent
            and (not self._seat_phase_over or self._waiting_for_close)
        ):
            # SendKeysToRfu carries a rolling high-byte liveness count even
            # for EMPTY keepalives.  Once the host sits, the follower sends
            # READY exactly once, then remains alive with EMPTY (0x11).
            if self._waiting_for_close:
                key_code = 0x17 if self._host_exit_room else 0x11
            else:
                key_code = 0x16 if self._host_ready and not self._self_ready_sent else 0x11
            if key_code == 0x16:
                self._self_ready_sent = True
                self._post_seat_delay = POST_SEAT_STANDBY_DELAY
                self._post_seat_barriers_remaining = 2
                self._post_seat_barrier_quiet = 0
            self._held_key_count = (self._held_key_count + 1) & 0xFF
            assert self._link is not None
            self._link.queue_uni(
                RfuSlot(
                    (
                        RfuCommand.SEND_HELD_KEYS,
                        (self._held_key_count << 8) | key_code,
                        0,
                        0,
                        0,
                        0,
                        0,
                    )
                )
            )
            self._flush_link_frames()
            return True
        return False

    def _on_link_clock(self) -> None:
        if self._cancel_retry_remaining is not None:
            if self._cancel_retry_remaining > 0:
                self._cancel_retry_remaining -= 1
            elif self._block_sender is None:
                self._cancel_retry_remaining = None
                self._start_block(link_command(LINKCMD_REQUEST_CANCEL))
        if self._animation_remaining is None:
            return
        if self._animation_remaining > 0:
            self._animation_remaining -= 1
            return
        self._animation_remaining = None
        self._ready_finish_sent = True
        self._start_block(link_command(LINKCMD_READY_FINISH_TRADE))
        if self._pending_confirm:
            self._pending_confirm = False
            self._commit()

    def _on_disconnect(self) -> None:
        if self._leaving:
            self._signals.append(FrlgWireSignal(FrlgWireSignalKind.EXITED))
        else:
            super()._on_disconnect()

    def _serve_request(self, request_type: int) -> None:
        if self._block_sender is None:
            if self._save_chain_active:
                # The normal end marker of the save chain is not a quiet
                # timeout: it is the leader returning to BufferTradeParties
                # and pulling our updated party again.
                self._save_chain_active = False
                self._save_barrier_quiet = 0
                self._barrier = BarrierResponder(
                    self._barrier.next_standby_count,
                    max_emits=LIVE_BARRIER_MAX_EMITS,
                )
            if (
                request_type in BLOCK_REQUEST_200
                and self._plan.link_player_sent
                and self._self_ready_sent
            ):
                # BufferTradeParties owns the UNI slot after the two post-seat
                # standby rounds.  Continuing SendHeldKeysToRfu into this
                # phase is an out-of-protocol command that the leader treats
                # as a communication error.
                self._seat_phase_over = True
            # A block request is a phase boundary.  Heartbeats that were
            # queued before it describe the previous RFU phase and can delay
            # even the initial LinkPlayer response by tens of seconds on a
            # real PIA reliable window.  Keep in-flight packets reliable, but
            # let the requested block claim the unsent queue immediately.
            assert self._wire is not None
            self._wire.discard_pending_child_idle_slots(
                discard_standby=request_type == BLOCK_REQUEST_TRAINER_CARD,
            )
            if request_type == BLOCK_REQUEST_TRAINER_CARD:
                self._entry_barrier_waiting = False
                # A card pull begins the next entry phase. An unanswered
                # count-0 standby belongs to the completed LinkPlayer phase;
                # do not re-emit it after this boundary, but retain the next
                # count for the card-completion barrier.
                self._barrier = BarrierResponder(
                    self._barrier.next_standby_count,
                    max_emits=LIVE_BARRIER_MAX_EMITS,
                )
            self._sending_entry_link = (
                request_type in BLOCK_REQUEST_200
                and not self._plan.link_player_sent
                and not self._host_in_seat
            )
            self._sending_trainer_card = (
                request_type == BLOCK_REQUEST_TRAINER_CARD and not self._host_in_seat
            )
            self._sending_menu_ribbons = (
                request_type == BLOCK_REQUEST_RIBBONS and self._seat_phase_over
            )
            self._start_block(self._plan.block_for_request(request_type))

    def _begin_entry_barrier_wait(self) -> None:
        self._entry_barrier_waiting = True

    def _begin_link_player_barrier_when_established(self) -> None:
        """Start entry standby only after both LinkPlayer records are applied.

        FRLG's host does not accept the follower's first standby response until
        it has finished publishing its own record *and* rebroadcasting the
        follower's final fragment at peer index 1.  The latter can trail the
        local sender by several hundred milliseconds on hardware.
        """
        if not (self._local_link_player_complete and self._host_link_player_complete):
            return
        if not self._barrier.active:
            # The quiet interval between our final LinkPlayer fragment and the
            # host's final fragment can enqueue many UNI idle heartbeats behind
            # a six-frame Reliable window. They are obsolete once both records
            # are established; retaining them delayed the first count-0
            # standby by 10–18 seconds on AX200 and let the host time out before
            # the character entered the room. Preserve block/K traffic, but
            # retire queued idle UNI slots so the barrier gets the next
            # sequence after the bounded in-flight window drains.
            assert self._wire is not None
            self._wire.discard_pending_child_idle_slots()
            self._barrier.begin(BarrierKind.STANDBY)
        self._begin_entry_barrier_wait()

    def _consume_host_block(self, count: int, data: bytes) -> None:
        if count == 2:
            command, cursor = parse_link_command(data)
            self._consume_link_command(command, cursor)
        elif count == 17:
            if is_link_player_block(data):
                self._host_link_player_complete = True
                self._begin_link_player_barrier_when_established()
            else:
                self._host_party.add(data)
        elif count == 4:
            if not self._host_party.complete:
                raise ProtocolStateError("FRLG ribbons arrived before the host party")
            self._host_ribbons_received = True
            self._maybe_announce_menu()

    def _consume_link_command(self, command: int, cursor: int) -> None:
        if command == LINKCMD_SET_MONS_TO_TRADE:
            if self._offered_slot is None:
                raise ProtocolStateError("FRLG leader selected Pokémon before follower offer")
            self._host_cursor = cursor
            self._start_block(link_command(LINKCMD_INIT_BLOCK))
        elif command == LINKCMD_START_TRADE:
            # Retransmitted leader blocks must not restart either the seam or
            # the 1935-frame animation clock.
            if self._animation_remaining is None and not self._ready_finish_sent:
                self._animation_remaining = self._trade_config.animation_frames
            if not self._scene_seam_started:
                self._scene_seam_started = True
                self._scene_seam_waiting = True
                self._scene_seam_quiet = 0
                if not self._barrier.active:
                    self._barrier.begin(BarrierKind.STANDBY)
        elif command == LINKCMD_CONFIRM_FINISH_TRADE:
            if self._ready_finish_sent:
                self._commit()
            else:
                self._pending_confirm = True
        elif command == LINKCMD_BOTH_CANCEL_TRADE:
            if self._leaving:
                self._cancel_retry_remaining = None
                self._cancel_exit_rounds_remaining = 2
                self._cancel_barrier_quiet = 0
                if not self._barrier.active:
                    self._barrier.begin(BarrierKind.STANDBY)
            else:
                self._signals.append(FrlgWireSignal(FrlgWireSignalKind.CANCELLED))
        elif command in {LINKCMD_PLAYER_CANCEL_TRADE, LINKCMD_PARTNER_CANCEL_TRADE}:
            # One-sided cancellation returns both games to the same menu.  A
            # follower that is leaving must select CANCEL again after the
            # message-dismiss delay; only the next mutual result can exit.
            self._cancel_retry_remaining = CANCEL_RESELECT_DELAY
        elif command == LINKCMD_REQUEST_CANCEL and self._leaving:
            # A human leader may select CANCEL while our retry delay is in
            # progress.  Reassert our own cancel on the next available slot
            # so the leader can resolve the pair to BOTH_CANCEL.
            self._cancel_retry_remaining = 0

    def _commit(self) -> None:
        if self._offered_slot is None or self._host_cursor is None:
            raise ProtocolStateError("FRLG confirmation lacks a selected local or remote Pokémon")
        received = self._host_party.selected(self._host_cursor)
        self._plan.replace(self._offered_slot, received)
        self._signals.append(FrlgWireSignal(FrlgWireSignalKind.TRADE_COMMITTED, received.party_bytes))
        self._host_party.reset()
        self._plan.begin_next_menu()
        self._offered_slot = None
        self._host_cursor = None
        self._ready_finish_sent = False
        self._pending_confirm = False
        self._menu_announced = False
        self._host_ribbons_received = False
        self._local_ribbons_complete = False
        self._scene_seam_started = False
        self._scene_seam_waiting = False
        self._scene_seam_quiet = 0
        self._save_chain_active = True
        self._save_barrier_quiet = 0
        if not self._barrier.active:
            self._barrier.begin(BarrierKind.STANDBY)

    def _start_block(self, data: bytes) -> None:
        if self._block_sender is not None:
            raise ProtocolStateError("FRLG attempted to overlap two child block sends")
        self._current_block = bytes(data)
        self._echoed_child_blocks = BlockReceiver(peer_count=2)
        self._echoed_last_fragment = False
        self._echo_retry_cursor = 0
        self._block_sender = BlockSender(self._current_block)

    def _finish_reflected_block(self) -> None:
        """Release one child send only after the leader's complete RFU echo."""
        self._block_sender = None
        self._current_block = None
        self._echoed_last_fragment = False
        self._echo_retry_cursor = 0
        if self._sending_entry_link:
            self._sending_entry_link = False
            self._local_link_player_complete = True
            self._begin_link_player_barrier_when_established()
        elif self._sending_trainer_card:
            self._sending_trainer_card = False
            if not self._barrier.active:
                self._barrier.begin(BarrierKind.STANDBY)
            self._begin_entry_barrier_wait()
        elif self._sending_menu_ribbons:
            self._sending_menu_ribbons = False
            self._local_ribbons_complete = True
            self._maybe_announce_menu()

    def _maybe_announce_menu(self) -> None:
        """Publish readiness only after both BufferTradeParties transfers finish."""
        if (
            not self._host_ribbons_received
            or not self._local_ribbons_complete
            or self._block_sender is not None
        ):
            return
        if self._awaiting_save:
            self._awaiting_save = False
            self._signals.append(FrlgWireSignal(FrlgWireSignalKind.SAVE_COMPLETE))
        elif not self._menu_announced:
            self._menu_announced = True
            self._signals.append(FrlgWireSignal(FrlgWireSignalKind.MENU_READY))
