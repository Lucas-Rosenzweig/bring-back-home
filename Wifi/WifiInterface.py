from abc import ABC, abstractmethod


class WifiInterface(ABC):

    @abstractmethod
    def create(self):
        pass

    @abstractmethod
    def delete(self):
        pass

    @abstractmethod
    def set_channel(self, channel: int):
        pass

    @abstractmethod
    def scan(self) -> bytes | None:
        pass
