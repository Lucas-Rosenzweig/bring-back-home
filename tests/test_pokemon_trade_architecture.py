from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTest(unittest.TestCase):
    def test_common_package_does_not_depend_on_reference_or_frlg_wire_layers(self) -> None:
        forbidden = {"ldn", "frlgsim"}
        for path in (ROOT / "pokemon_trade").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(
                    any(name.split(".")[0] in forbidden for name in names),
                    f"forbidden dependency in {path}",
                )

    def test_legacy_ldn_core_is_not_imported_by_the_common_api(self) -> None:
        common_modules = (ROOT / "pokemon_trade").glob("*.py")
        for path in common_modules:
            self.assertNotIn("ldn_protocol", path.read_text(encoding="utf-8"))
