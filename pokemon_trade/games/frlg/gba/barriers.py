"""Follower-side RFU standby and close-link barrier coordination."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pokemon_trade.games.frlg.gba.rfu import RfuCommand, RfuSlot


class BarrierKind(StrEnum):
    STANDBY = "standby"
    CLOSE = "close"


@dataclass(slots=True)
class BarrierResponder:
    """Mirrors host barriers and initiates follower barriers with explicit counts."""

    next_standby_count: int = 0
    max_emits: int | None = None
    kind: BarrierKind | None = None
    initiated: bool = False
    host_count: int | None = None
    _emits: int = 0
    _completion_reply: RfuSlot | None = None

    @property
    def active(self) -> bool:
        return self.kind is not None or self._completion_reply is not None

    def begin(self, kind: BarrierKind) -> None:
        if self.kind is None and self._completion_reply is None:
            self.kind = kind
            self.initiated = True
            self.host_count = None
            self._emits = 0
        elif self.kind is not kind:
            raise RuntimeError("cannot change RFU barrier kind before completion")

    def observe(self, slot: RfuSlot) -> bool:
        """Observe a host slot and return True only when a local barrier completes."""
        command = slot.command
        if command not in {RfuCommand.READY_EXIT_STANDBY, RfuCommand.READY_CLOSE_LINK}:
            return False
        observed_kind = (
            BarrierKind.STANDBY
            if command is RfuCommand.READY_EXIT_STANDBY
            else BarrierKind.CLOSE
        )
        count = slot.words[1]
        if self._completion_reply is not None:
            # The host can repeat its ready slot before the next local VBlank.
            # Keep the already queued final reply instead of reopening the
            # completed round as a host-initiated barrier.
            return False
        if self.kind is None:
            if (
                observed_kind is BarrierKind.STANDBY
                and count != self.next_standby_count
                and 0 < ((self.next_standby_count - count) & 0xFFFF) < 0x8000
            ):
                # A leader may repeat the preceding count after the follower
                # has completed that round. Reopening it would regress the
                # local counter and keep stale standby traffic alive.
                return False
            self.kind, self.initiated, self.host_count = observed_kind, False, count
            self._emits = 0
            if observed_kind is BarrierKind.STANDBY:
                self.next_standby_count = count
            return False
        if self.kind is not observed_kind:
            return False
        self.host_count = count
        if self.initiated and (observed_kind is BarrierKind.CLOSE or count == self.next_standby_count):
            # Our bounded burst may have arrived before the host installed its
            # matching barrier callback. Its first matching ready slot proves
            # that the callback is active, so answer it once on the next
            # VBlank before retiring the round.
            self._completion_reply = RfuSlot(
                (slot.words[0] & 0xFF00, count, 0, 0, 0, 0, 0)
            )
            if observed_kind is BarrierKind.STANDBY:
                self.next_standby_count = (self.next_standby_count + 1) & 0xFFFF
            self.kind, self.initiated = None, False
            self._emits = 0
            return True
        return False

    def outgoing(self) -> RfuSlot | None:
        if self._completion_reply is not None:
            reply = self._completion_reply
            self._completion_reply = None
            return reply
        if self.kind is None:
            return None
        if self.max_emits is not None and self._emits >= self.max_emits:
            return None
        count = self.next_standby_count if self.kind is BarrierKind.STANDBY else (self.host_count or self.next_standby_count)
        command = (
            RfuCommand.READY_EXIT_STANDBY
            if self.kind is BarrierKind.STANDBY
            else RfuCommand.READY_CLOSE_LINK
        )
        self._emits += 1
        return RfuSlot((command, count, 0, 0, 0, 0, 0))

    def rearm(self) -> None:
        """Permit another bounded burst for an unanswered active barrier."""
        if self.kind is not None:
            self._emits = 0
