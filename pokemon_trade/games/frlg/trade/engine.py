"""Explicit FRLG transaction state machine above the game wire adapter."""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_trade.api import TradeEvent, TradeEventKind, TradeRequest, TradeResult, TradeStatus
from pokemon_trade.artifacts import PokemonArtifact
from pokemon_trade.errors import PeerDisconnectedError, ProtocolStateError, TradeCancelledError, TradeTimeoutError
from pokemon_trade.games.frlg.pokemon import FrlgTeam, Pk3
from pokemon_trade.games.frlg.trade.model import (
    FrlgCommand,
    FrlgCommandKind,
    FrlgTradePhase,
    FrlgWireSignal,
    FrlgWireSignalKind,
)

DEFAULT_FRLG_PHASE_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True, slots=True)
class FrlgProtocolTuning:
    # Entry is intentionally slow on the validated AX200 path: the observed
    # LinkPlayer-to-menu interval can exceed 50 seconds while Reliable drains
    # the card and party barriers. Keep the default above that measured tail.
    phase_timeout_seconds: float = DEFAULT_FRLG_PHASE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.phase_timeout_seconds <= 0:
            raise ValueError("phase timeout must be positive")


class FrlgTradeEngine:
    """Commits local state only after `TRADE_COMMITTED` carries a valid `.pk3`."""

    def __init__(self, request: TradeRequest, *, tuning: FrlgProtocolTuning = FrlgProtocolTuning()) -> None:
        self.request = request
        self.tuning = tuning
        self._team = FrlgTeam.from_artifacts(request.team)
        self._received: list[Pk3] = []
        self._round = 0
        self._phase = FrlgTradePhase.AWAIT_PEER
        self._deadline: float | None = None
        self._terminal_error: Exception | None = None

    @property
    def phase(self) -> FrlgTradePhase:
        return self._phase

    @property
    def result(self) -> TradeResult | None:
        if self._phase is FrlgTradePhase.COMPLETED:
            return TradeResult(TradeStatus.COMPLETED, self._artifacts(), self._team.artifacts())
        if self._phase is FrlgTradePhase.CANCELLED:
            return TradeResult(TradeStatus.CANCELLED, self._artifacts(), self._team.artifacts(), self._error_text())
        if self._phase is FrlgTradePhase.FAILED:
            status = TradeStatus.PARTIAL if self._received else TradeStatus.FAILED
            return TradeResult(status, self._artifacts(), self._team.artifacts(), self._error_text())
        return None

    def start(self, now: float) -> tuple[tuple[FrlgCommand, ...], tuple[TradeEvent, ...]]:
        return self._set_deadline(now), ()

    def receive(
        self, signal: FrlgWireSignal, now: float
    ) -> tuple[tuple[FrlgCommand, ...], tuple[TradeEvent, ...]]:
        if self.result is not None:
            raise ProtocolStateError("received an FRLG wire signal after terminal state")
        if signal.kind is FrlgWireSignalKind.CANCELLED:
            return self._cancel(TradeCancelledError("trade cancelled by peer"))
        if signal.kind is FrlgWireSignalKind.PEER_DISCONNECTED:
            return self._fail(PeerDisconnectedError("FRLG peer disconnected"))
        if self._phase is FrlgTradePhase.AWAIT_PEER:
            self._expect(signal, FrlgWireSignalKind.PEER_CONNECTED)
            self._phase = FrlgTradePhase.AWAIT_ROOM
            return self._set_deadline(now), (TradeEvent(TradeEventKind.PEER_CONNECTED),)
        if self._phase is FrlgTradePhase.AWAIT_ROOM:
            self._expect(signal, FrlgWireSignalKind.ROOM_ENTERED)
            self._phase = FrlgTradePhase.AWAIT_MENU
            return self._set_deadline(now), (TradeEvent(TradeEventKind.ROOM_ENTERED),)
        if self._phase is FrlgTradePhase.AWAIT_MENU:
            self._expect(signal, FrlgWireSignalKind.MENU_READY)
            self._phase = FrlgTradePhase.AWAIT_COMMIT
            slot = self.request.offered_slots[self._round]
            self._set_deadline(now)
            return (FrlgCommand(FrlgCommandKind.OFFER_SLOT, slot),), (
                TradeEvent(TradeEventKind.MENU_READY),
                TradeEvent(TradeEventKind.OFFERED, self._round + 1),
            )
        if self._phase is FrlgTradePhase.AWAIT_COMMIT:
            self._expect(signal, FrlgWireSignalKind.TRADE_COMMITTED)
            assert signal.received_pk3 is not None
            received = Pk3.parse(signal.received_pk3)
            slot = self.request.offered_slots[self._round]
            self._team = self._team.replace(slot, received)
            self._received.append(received)
            self._round += 1
            event = TradeEvent(TradeEventKind.COMMITTED, self._round)
            trade_count = self.request.trade_count
            assert trade_count is not None  # normalized by TradeRequest.__post_init__
            if self._round < trade_count:
                self._phase = FrlgTradePhase.AWAIT_MENU
                return self._set_deadline(now), (event,)
            self._phase = FrlgTradePhase.AWAIT_SAVE
            self._set_deadline(now)
            return (FrlgCommand(FrlgCommandKind.SAVE),), (event, TradeEvent(TradeEventKind.SAVING))
        if self._phase is FrlgTradePhase.AWAIT_SAVE:
            self._expect(signal, FrlgWireSignalKind.SAVE_COMPLETE)
            self._phase = FrlgTradePhase.AWAIT_EXIT
            self._set_deadline(now)
            return (FrlgCommand(FrlgCommandKind.LEAVE),), (TradeEvent(TradeEventKind.LEAVING),)
        if self._phase is FrlgTradePhase.AWAIT_EXIT:
            self._expect(signal, FrlgWireSignalKind.EXITED)
            self._deadline = None
            if isinstance(self._terminal_error, TradeCancelledError):
                # A caller can still stop after an earlier round committed.
                # Preserve that durable result as an explicit partial outcome
                # instead of hiding it behind the cancellation status.
                self._phase = (
                    FrlgTradePhase.FAILED if self._received else FrlgTradePhase.CANCELLED
                )
                return (), (TradeEvent(TradeEventKind.CANCELLED),)
            self._phase = FrlgTradePhase.COMPLETED
            return (), (TradeEvent(TradeEventKind.COMPLETED),)
        raise AssertionError("unreachable FRLG trade phase")

    def cancel(self) -> tuple[tuple[FrlgCommand, ...], tuple[TradeEvent, ...]]:
        if self.result is not None:
            return (), ()
        self._phase = FrlgTradePhase.AWAIT_EXIT
        self._terminal_error = TradeCancelledError("trade cancelled by caller")
        return (FrlgCommand(FrlgCommandKind.LEAVE),), (TradeEvent(TradeEventKind.LEAVING),)

    def check_timeout(self, now: float) -> None:
        if self._deadline is not None and now >= self._deadline:
            previous_phase = self._phase
            self._phase = FrlgTradePhase.FAILED
            self._terminal_error = TradeTimeoutError(f"FRLG timeout during {previous_phase}")
            self._deadline = None
            raise self._terminal_error

    def _set_deadline(self, now: float) -> tuple[FrlgCommand, ...]:
        self._deadline = now + self.tuning.phase_timeout_seconds
        return ()

    def _expect(self, signal: FrlgWireSignal, expected: FrlgWireSignalKind) -> None:
        if signal.kind is not expected:
            raise ProtocolStateError(f"expected {expected}, received {signal.kind}")

    def _cancel(self, error: Exception) -> tuple[tuple[FrlgCommand, ...], tuple[TradeEvent, ...]]:
        self._phase = FrlgTradePhase.FAILED if self._received else FrlgTradePhase.CANCELLED
        self._deadline = None
        self._terminal_error = error
        return (), (TradeEvent(TradeEventKind.CANCELLED),)

    def _fail(self, error: Exception) -> tuple[tuple[FrlgCommand, ...], tuple[TradeEvent, ...]]:
        self._phase = FrlgTradePhase.FAILED
        self._deadline = None
        self._terminal_error = error
        return (), (TradeEvent(TradeEventKind.FAILED),)

    def _artifacts(self) -> tuple[PokemonArtifact, ...]:
        return tuple(pokemon.to_artifact() for pokemon in self._received)

    def _error_text(self) -> str | None:
        return str(self._terminal_error) if self._terminal_error is not None else None
