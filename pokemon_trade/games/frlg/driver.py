"""Live follower driver joining PIA and the RFU link below the trade machine.

This module deliberately stops before menu selection.  A command that would
change a Pokémon team is rejected until the FRLG block-to-menu mapping has a
captured, synthetic replay test.  It is still useful on hardware: it performs
the same encrypted PIA and RFU C/A/NI work that the future transaction driver
will use and exposes only evidence-backed link milestones.
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import trio

from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.gba.frame import ControlFrame, FrameType
from pokemon_trade.games.frlg.gba.link import RfuFollowerLink
from pokemon_trade.games.frlg.gba.rfu import RfuSlot
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.session import PiaSession
from pokemon_trade.games.frlg.pia.wire import FrlgPiaWire
from pokemon_trade.games.frlg.trade.model import (
    FrlgCommand,
    FrlgCommandKind,
    FrlgWireSignal,
    FrlgWireSignalKind,
)
from pokemon_trade.transport.base import DatagramTransport


FRLG_VBLANK_SECONDS = 1 / 59.7275
PIA_JOIN_RETRY_SECONDS = 0.5
RFU_SLOT_CREDIT_MAX = 2


@dataclass(frozen=True, slots=True)
class FrlgLiveWireConfig:
    """Local, non-loggable PIA/RFU values supplied by the live runner.

    ``game_key`` is intentionally injected.  The package neither knows nor
    stores a title key, a real player identity, or a capture-derived station
    identifier.
    """

    game_key: bytes
    pia_constant_id: bytes
    player_name: str
    rfu_connect_id: bytes
    rfu_game_data: bytes
    random_nonce: bytes | None = None
    local_variable_id: int | None = None
    packet_nonces: tuple[bytes, ...] = ()
    player_id: bytes = bytes.fromhex("00000000000000010000000000000000")
    frame_interval_seconds: float = FRLG_VBLANK_SECONDS
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if len(self.game_key) not in {16, 24, 32}:
            raise ValueError("FRLG PIA game_key must be an AES key")
        if len(self.pia_constant_id) != 6:
            raise ValueError("FRLG PIA constant ID must contain six bytes")
        if not self.player_name or len(self.player_name.encode("utf-8")) > 20:
            raise ValueError("FRLG PIA player name must contain one to 20 UTF-8 bytes")
        if len(self.rfu_connect_id) != 2:
            raise ValueError("FRLG RFU connect ID must contain two bytes")
        if self.random_nonce is not None and len(self.random_nonce) != 4:
            raise ValueError("FRLG PIA random nonce must contain four bytes")
        if self.local_variable_id is not None and not 2 <= self.local_variable_id <= 0xFFFF:
            raise ValueError("FRLG PIA local variable ID must be from 2 through 65535")
        if any(len(nonce) != 8 for nonce in self.packet_nonces):
            raise ValueError("FRLG PIA packet nonces must each contain eight bytes")
        if len(self.player_id) != 16:
            raise ValueError("FRLG PIA player ID must contain 16 bytes")
        if self.frame_interval_seconds <= 0:
            raise ValueError("FRLG frame interval must be positive")
        for field_name in ("game_key", "pia_constant_id", "rfu_connect_id", "rfu_game_data", "player_id"):
            object.__setattr__(self, field_name, bytes(getattr(self, field_name)))
        if self.random_nonce is not None:
            object.__setattr__(self, "random_nonce", bytes(self.random_nonce))
        object.__setattr__(self, "packet_nonces", tuple(map(bytes, self.packet_nonces)))


class FrlgPiaRfuDriver:
    """Cadenced PIA/RFU follower adapter implementing ``FrlgWireDriver``."""

    def __init__(self, transport: DatagramTransport, config: FrlgLiveWireConfig) -> None:
        self._transport = transport
        self._config = config
        self._clock = config.clock
        self._wire: FrlgPiaWire | None = None
        self._link: RfuFollowerLink | None = None
        self._signals: deque[FrlgWireSignal] = deque()
        self._link_started = False
        self._host_uni_entered = False
        self._slot_credit = 0
        self._pia_join: tuple[bytes, int] | None = None
        self._next_pia_join_at: float | None = None
        self._next_vblank_at: float | None = None
        self._closed = False
        self._disconnect_sent = False

    async def start(self) -> None:
        if self._wire is not None:
            raise RuntimeError("FRLG PIA/RFU driver has already started")
        nonce = self._config.random_nonce or secrets.token_bytes(4)
        session = PiaSession(
            local_constant_id=self._config.pia_constant_id,
            local_ip=self._transport.session.local.ip_address,
            player_name=self._config.player_name,
            random_nonce=nonce,
            app_version=self._transport.session.app_version,
            player_id=self._config.player_id,
        )
        packet_nonces = iter(self._config.packet_nonces)

        def packet_nonce(size: int) -> bytes:
            if size != 8:
                raise ValueError("FRLG PIA requested a non-eight-byte packet nonce")
            try:
                return next(packet_nonces)
            except StopIteration as error:
                raise ProtocolStateError("FRLG replay exhausted its packet nonces") from error

        peer = PiaPeer(
            session,
            ssid=self._transport.session.ssid,
            game_key=self._config.game_key,
            local_ip=self._transport.session.local.ip_address,
            nonce_source=(packet_nonce if self._config.packet_nonces else None),
        )
        self._wire = FrlgPiaWire(peer, clock=self._clock)
        host_constant_id = bytes.fromhex(
            self._transport.session.host.mac_address.replace(":", "")
        )
        if len(host_constant_id) != 6:
            raise ValueError("LDN host MAC must contain six octets")
        # PIA reserves variable ID zero for the initial host-directed request
        # and ID one for session-control headers.
        local_variable_id = self._config.local_variable_id
        if local_variable_id is None:
            local_variable_id = secrets.randbelow(0xFFFE) + 2
        self._pia_join = (host_constant_id, local_variable_id)
        self._wire.begin(*self._pia_join)
        self._next_pia_join_at = self._clock() + PIA_JOIN_RETRY_SECONDS
        self._next_vblank_at = self._clock() + self._config.frame_interval_seconds
        self._link = RfuFollowerLink(self._config.rfu_connect_id, self._config.rfu_game_data)

    async def send(self, command: FrlgCommand) -> None:
        self._ensure_started()
        if command.kind is FrlgCommandKind.LEAVE:
            await self._disconnect_now()
            return
        raise ProtocolStateError(
            f"FRLG {command.kind} requires an unverified menu/block mapping; refusing live input"
        )

    async def receive(self) -> FrlgWireSignal:
        self._ensure_started()
        while not self._signals:
            datagram = None
            now = self._clock()
            assert self._next_vblank_at is not None
            with trio.move_on_after(max(0.0, self._next_vblank_at - now)) as tick:
                datagram = await self._transport.receive()
            if tick.cancelled_caught:
                await self._advance_vblank_clock()
                await self._flush()
                continue
            assert datagram is not None
            self._ingest(datagram.payload, datagram.source[0])
            await self._advance_vblank_clock()
            await self._flush()
        return self._signals.popleft()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if (
            self._wire is not None
            and self._wire.peer.session.connected
            and not self._disconnect_sent
        ):
            with trio.move_on_after(0.25, shield=True):
                await self._disconnect_now()

    async def _disconnect_now(self) -> None:
        """Queue and flush the emulator disconnect frame at most once."""
        if self._disconnect_sent:
            return
        self._disconnect_sent = True
        self._queue_frame(ControlFrame(FrameType.DISCONNECT, b"").encode())
        await self._flush()

    def _ingest(self, datagram: bytes, source_ip: str) -> None:
        assert self._wire is not None
        frames = self._wire.receive_datagram(datagram, source_ip)
        if self._wire.peer.session.connected and not self._link_started:
            self._link_started = True
            self._signals.append(FrlgWireSignal(FrlgWireSignalKind.PEER_CONNECTED))
            assert self._link is not None
            self._queue_frame(self._link.start(), initialized=True)
        for frame in frames:
            assert self._link is not None
            # Timestamp K acknowledgements name their position in our outgoing
            # PIA envelope.  They are deliberately emitted in a one-message
            # envelope by ``drain_datagrams``, so their index is always one.
            inbound = self._link.receive(frame, message_index=1)
            if inbound.host_poll_received:
                self._slot_credit = min(self._slot_credit + 1, RFU_SLOT_CREDIT_MAX)
            self._flush_link_frames()
            # ``A`` accepts the emulator-side connection.  The host's first
            # UNI LLSF proves only that both RFU peers left NI; the game can
            # still be parked outside the trade room while LinkPlayer blocks
            # and the entry barrier are exchanged.  The trade adapter emits
            # the semantic ROOM_ENTERED signal from later game-layer evidence.
            if inbound.host_uni_entered:
                self._host_uni_entered = True
            if inbound.positional_slots:
                self._on_rfu_slots(inbound.positional_slots)
            if isinstance(frame, ControlFrame) and frame.frame_type is FrameType.DISCONNECT:
                self._on_disconnect()
        # A retransmission clock cannot rely only on receive timeouts: an RFU
        # parent retries aggressively, so an active host can otherwise keep
        # this loop continuously busy and starve its own reliable ACKs.
        self._wire.poll_retransmissions()

    def _link_tick(self) -> None:
        if self._wire is None:
            return
        if not self._wire.peer.session.connected:
            now = self._clock()
            if (
                self._wire.peer.session.host_variable_id is None
                and self._pia_join is not None
                and self._next_pia_join_at is not None
                and now >= self._next_pia_join_at
            ):
                # The v6 session join has no reliable channel underneath it;
                # repeat it at PIA's documented session-request cadence until
                # the host establishes the mesh connection.
                self._wire.begin(*self._pia_join)
                self._next_pia_join_at = now + PIA_JOIN_RETRY_SECONDS
            return
        if self._link is None or not self._link_started:
            return
        # Wall-clock game timers must advance once per VBlank even while a
        # full Reliable window or absent host poll prevents transmission.
        self._on_link_clock()
        # Do not advance NI or the game FSM unless its resulting child slot
        # can be assigned a Reliable sequence now.  Queuing through a full
        # window lets several historical VBlanks burst into one later PIA
        # datagram; the host emulator consumes only one and silently loses the
        # rest, commonly leaving its LinkPlayer block one fragment short.
        self._wire.poll_retransmissions()
        if not self._wire.can_queue_child_slot or self._slot_credit <= 0:
            return
        was_ready_for_uni = self._link.ready_for_uni
        self._link.tick()
        emitted = self._flush_link_frames()
        if was_ready_for_uni and self._link.ready_for_uni:
            game_emitted = self._on_vblank()
            if not game_emitted:
                # ``SendRfuData`` emits a child emulator slot every VBlank.
                # A quiet game layer is represented by an all-zero UNI slot,
                # never by an absent PIA frame; otherwise the host remains
                # parked at its entry poll after the LinkPlayer exchange.
                self._link.queue_uni(RfuSlot.idle())
                emitted += self._flush_link_frames()
            elif not emitted:
                # Subclasses currently flush their game slot immediately.
                # Count that slot even though it is no longer in link.drain().
                emitted = 1
        if emitted:
            self._slot_credit -= 1
        self._wire.poll_retransmissions()

    async def _advance_vblank_clock(self) -> None:
        """Advance at most one RFU VBlank and flush it before another tick.

        A delayed userspace receive must not turn missed VBlanks into a burst
        of child ``T`` slots: the emulator accepts at most one new child slot
        per VBlank.  Reliable retransmission, rather than a catch-up replay,
        recovers an interrupted cadence.
        """
        assert self._next_vblank_at is not None
        now = self._clock()
        if now >= self._next_vblank_at:
            self._link_tick()
            await self._flush()
            # Do not accumulate a catch-up debt. The next actual VBlank starts
            # a fresh cadence interval after this emitted slot.
            self._next_vblank_at = now + self._config.frame_interval_seconds

    def _on_rfu_slots(self, slots: tuple[tuple[int, RfuSlot], ...]) -> None:
        """Subclass hook for host UNI slots after link-layer ACKs are queued."""

    def _on_vblank(self) -> bool:
        """Return whether a subclass queued its own UNI slot for this VBlank."""
        return False

    def _on_link_clock(self) -> None:
        """Subclass hook for timers that must not be gated by RFU emission."""

    def _on_disconnect(self) -> None:
        """Subclass hook for the final emulator disconnect control frame."""
        self._signals.append(FrlgWireSignal(FrlgWireSignalKind.PEER_DISCONNECTED))

    def _flush_link_frames(self) -> int:
        assert self._link is not None
        frames = self._link.drain()
        for frame in frames:
            self._queue_frame(frame)
        return len(frames)

    def _queue_frame(self, frame: bytes, *, initialized: bool = False) -> None:
        assert self._wire is not None
        self._wire.queue_frame(frame, initialized=initialized)

    async def _flush(self) -> None:
        assert self._wire is not None
        for datagram in self._wire.drain_datagrams():
            await self._transport.send(
                datagram,
                (self._transport.session.host.ip_address, 12345),
            )

    def _ensure_started(self) -> None:
        if self._closed:
            raise RuntimeError("FRLG PIA/RFU driver is closed")
        if self._wire is None or self._link is None:
            raise RuntimeError("FRLG PIA/RFU driver has not started")
