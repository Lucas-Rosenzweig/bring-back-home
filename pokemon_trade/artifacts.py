"""Pokémon artifacts and safe, explicit persistence helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pokemon_trade.errors import InvalidArtifactError


@dataclass(frozen=True, slots=True)
class PokemonArtifact:
    """A received or offered Pokémon in a game-owned portable format."""

    format: str
    data: bytes
    generation: int
    suggested_name: str = "pokemon"
    metadata: Mapping[str, str | int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.format or not self.format.isascii() or not self.format.islower():
            raise InvalidArtifactError("artifact format must be a lowercase ASCII name")
        if not self.data:
            raise InvalidArtifactError("artifact data must not be empty")
        if self.generation < 1:
            raise InvalidArtifactError("artifact generation must be positive")
        if not self.suggested_name:
            raise InvalidArtifactError("artifact suggested_name must not be empty")
        object.__setattr__(self, "data", bytes(self.data))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def export_artifacts(
    artifacts: tuple[PokemonArtifact, ...], output_directory: Path
) -> tuple[Path, ...]:
    """Atomically write already-committed artifacts using neutral filenames.

    Persistence is deliberately separate from a protocol run.  A caller can
    only pass artifacts returned after a plugin has committed an exchange.
    """
    output_directory.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for index, artifact in enumerate(artifacts, start=1):
        destination = output_directory / f"trade-{index:02d}.{artifact.format}"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(artifact.data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            finally:
                raise
        results.append(destination)
    return tuple(results)
