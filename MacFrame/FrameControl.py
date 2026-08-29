class FrameControl:
    def __init__(self, raw : bytes) -> None:

        if len(raw) != 2:
            raise ValueError("Frame control must be 2 bytes long")

        self.raw : bytes = raw
        self._value :int = int.from_bytes(raw, "little" )

    @property
    def protocol_version(self) -> int:
        return (self._value >> 2) & 0b11

    @property
    def type(self) -> int:
        return (self._value >> 2) & 0b11

    @property
    def subtype(self) -> int:
        return (self._value >> 4) & 0b1111

    @property
    def to_ds(self) -> int:
        return (self._value >> 8) & 1

    @property
    def from_ds(self) -> int:
        return (self._value >> 9) & 1

    @property
    def more_fragments(self) -> int:
        return (self._value >> 10) & 1

    @property
    def retry(self) -> int:
        return (self._value >> 11) & 1

    @property
    def power_management(self) -> int:
        return (self._value >> 12) & 1

    @property
    def more_data(self) -> int:
        return (self._value >> 13) & 1

    @property
    def protected_frame(self) -> int:
        return (self._value >> 14) & 1

    @property
    def plus_htc_order(self) -> int:
        return (self._value >> 15) & 1

    def print(self) -> None:
        print("Frame Control:")
        print(f"  Raw                : {self.raw.hex(' ')}")
        print(f"  Value              : 0x{self._value:04X}")
        print(f"  Protocol Version   : {self.protocol_version}")
        print(f"  Type               : {self.type}")
        print(f"  Subtype            : {self.subtype}")
        print(f"  To DS              : {self.to_ds}")
        print(f"  From DS            : {self.from_ds}")
        print(f"  More Fragments     : {self.more_fragments}")
        print(f"  Retry              : {self.retry}")
        print(f"  Power Management   : {self.power_management}")
        print(f"  More Data          : {self.more_data}")
        print(f"  Protected Frame    : {self.protected_frame}")
        print(f"  +HTC / Order       : {self.plus_htc_order}")
