"""FRLG child NI data transfer over RFU LLSF slots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from pokemon_trade.games.frlg.gba.rfu import ChildLlsf, LlsfState

WINDOWS = 4
CHILD_PAYLOAD_SIZE = 12


class NiState(IntEnum):
    START = 1
    DATA = 2
    END = 3
    NULL = 4
    DONE = 5


@dataclass(slots=True)
class NiSender:
    """One-pass sender paced by caller ticks; PIA provides lower-layer reliability."""

    data: bytes
    data_type: int = 1
    state: NiState = NiState.START
    _offset: int = 0

    @property
    def done(self) -> bool:
        return self.state is NiState.DONE

    def next_slot(self) -> bytes | None:
        if self.state is NiState.DONE:
            return None
        if self.state is NiState.START:
            header = bytes((self.data_type,)) + CHILD_PAYLOAD_SIZE.to_bytes(2, "little") + len(self.data).to_bytes(4, "little")
            self.state = NiState.DATA
            return ChildLlsf(LlsfState.NI_START, n=1, size=len(header)).encode() + header
        if self.state is NiState.DATA:
            if self._offset < len(self.data):
                phase = (self._offset // CHILD_PAYLOAD_SIZE) % WINDOWS
                payload = self.data[self._offset : self._offset + CHILD_PAYLOAD_SIZE]
                self._offset += len(payload)
                return ChildLlsf(LlsfState.NI, n=1, phase=phase, size=len(payload)).encode() + payload
            self.state = NiState.END
        if self.state is NiState.END:
            self.state = NiState.NULL
            return ChildLlsf(LlsfState.NI_END).encode()
        self.state = NiState.DONE
        return ChildLlsf(LlsfState.NULL, n=1).encode()


def acknowledgement_for_parent_ni(state: LlsfState, n: int, phase: int) -> bytes | None:
    if state not in {LlsfState.NI_START, LlsfState.NI, LlsfState.NI_END}:
        return None
    return ChildLlsf(state, n=n, phase=phase, acknowledge=True).encode()
