from abc import ABC, abstractmethod


class NintendoLdnPayload(ABC):
    raw: bytes

    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.parse()

    @abstractmethod
    def parse(self) -> None:
        pass

    @abstractmethod
    def print(self, indent: str = "") -> None:
        pass
