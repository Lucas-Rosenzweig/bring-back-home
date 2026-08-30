class ByteReader:
    def __init__(self, raw: bytes) -> None:
        self._raw: bytes = raw
        self._offset: int = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def remaining(self) -> int:
        return len(self._raw) - self._offset

    def read_bytes(self, size: int, field: str = "data") -> bytes:
        if size < 0:
            raise ValueError("Read size must not be negative")
        if self.remaining < size:
            message = (
                f"Truncated {field} at offset {self._offset}: expected {size} bytes, "
                + f"only {self.remaining} available"
            )
            raise ValueError(message)

        end = self._offset + size
        value = self._raw[self._offset:end]
        self._offset = end
        return value

    def read_u8(self, field: str = "uint8") -> int:
        return self.read_bytes(1, field)[0]

    def read_u16_be(self, field: str = "uint16") -> int:
        return int.from_bytes(self.read_bytes(2, field), "big")

    def read_remaining(self) -> bytes:
        return self.read_bytes(self.remaining, "remaining data")
