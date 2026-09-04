"""Typed protocol-neutral events exchanged with the FRLG wire adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FrlgWireSignalKind(StrEnum):
    PEER_CONNECTED = "peer_connected"
    ROOM_ENTERED = "room_entered"
    MENU_READY = "menu_ready"
    TRADE_COMMITTED = "trade_committed"
    SAVE_COMPLETE = "save_complete"
    EXITED = "exited"
    CANCELLED = "cancelled"
    PEER_DISCONNECTED = "peer_disconnected"


@dataclass(frozen=True, slots=True)
class FrlgWireSignal:
    kind: FrlgWireSignalKind
    received_pk3: bytes | None = None

    def __post_init__(self) -> None:
        if self.kind is FrlgWireSignalKind.TRADE_COMMITTED and self.received_pk3 is None:
            raise ValueError("a committed FRLG trade must include a received .pk3")
        if self.kind is not FrlgWireSignalKind.TRADE_COMMITTED and self.received_pk3 is not None:
            raise ValueError("only a commit signal may include a received .pk3")
        if self.received_pk3 is not None:
            object.__setattr__(self, "received_pk3", bytes(self.received_pk3))


class FrlgCommandKind(StrEnum):
    OFFER_SLOT = "offer_slot"
    SAVE = "save"
    LEAVE = "leave"


@dataclass(frozen=True, slots=True)
class FrlgCommand:
    kind: FrlgCommandKind
    slot: int | None = None

    def __post_init__(self) -> None:
        if self.kind is FrlgCommandKind.OFFER_SLOT and self.slot is None:
            raise ValueError("an offer command requires a party slot")
        if self.kind is not FrlgCommandKind.OFFER_SLOT and self.slot is not None:
            raise ValueError("only an offer command may include a party slot")


class FrlgTradePhase(StrEnum):
    AWAIT_PEER = "await_peer"
    AWAIT_ROOM = "await_room"
    AWAIT_MENU = "await_menu"
    AWAIT_COMMIT = "await_commit"
    AWAIT_SAVE = "await_save"
    AWAIT_EXIT = "await_exit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
