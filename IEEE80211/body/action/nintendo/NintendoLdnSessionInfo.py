class NintendoLdnSessionInfo:
    SIZE = 32

    def __init__(self, raw: bytes) -> None:
        if len(raw) != self.SIZE:
            raise ValueError("Nintendo LDN session info must be 32 bytes long")
        self.raw = raw

    def print(self, indent: str = "") -> None:
        print(f"{indent}Session Info        : {self.raw.hex(' ')}")
