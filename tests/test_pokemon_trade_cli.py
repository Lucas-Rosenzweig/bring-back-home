from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_trade.api import TradeRequest, TradeResult, TradeStatus
from pokemon_trade.artifacts import PokemonArtifact
from pokemon_trade_cli import (
    PROJECT_ROOT,
    _arguments,
    _display_diagnostics,
    _find_trade_error,
    main,
)


class PokemonTradeCliTest(unittest.TestCase):
    def test_non_completed_result_is_a_nonzero_cli_exit(self) -> None:
        failed = TradeResult(TradeStatus.FAILED, (), (), "peer disconnected")
        request = TradeRequest((PokemonArtifact("pk3", bytes(100), 3),))
        with (
            patch("pokemon_trade_cli._request", return_value=request),
            patch("pokemon_trade_cli.FrlgTeam.from_artifacts"),
            patch("pokemon_trade_cli.trio.run", return_value=failed),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "--replay", "synthetic.jsonl", "--game", "firered", "--trainer-id", "1",
                    "--secret-id", "2", "--name", "EMU", "offered.pk3",
                ]), 1)

    def test_extracts_a_public_trade_error_from_cleanup_group(self) -> None:
        from pokemon_trade.errors import TradeTimeoutError

        expected = TradeTimeoutError("timed out")
        error = ExceptionGroup("cleanup", [ExceptionGroup("nested", [expected])])
        self.assertIs(_find_trade_error(error), expected)

    def test_help_and_required_identity_contract(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            _arguments(["--help"])
        self.assertEqual(error.exception.code, 0)

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            _arguments(["offered.pk3"])
        self.assertEqual(error.exception.code, 2)

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            _arguments([
                "--variant", "firered", "--trainer-id", "1", "--secret-id", "2",
                "--name", "EMU", "offered.pk3",
            ])
        self.assertEqual(error.exception.code, 2)

    def test_parses_live_and_replay_options_without_protocol_logic(self) -> None:
        args = _arguments(
            [
                "--game", "firered", "--trainer-id", "1", "--secret-id", "2", "--name", "EMU",
                "--slots", "0,1", "--disconnect-after-trade",
                "--replay", "synthetic.jsonl", "a.pk3", "b.pk3",
            ]
        )
        self.assertEqual(args.slots, (0, 1))
        self.assertEqual(args.replay.name, "synthetic.jsonl")
        self.assertEqual(args.phase_timeout, 90.0)
        self.assertEqual(args.game, "firered")
        self.assertTrue(args.disconnect_after_trade)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _arguments(
                [
                    "--game", "firered", "--trainer-id", "1", "--secret-id", "2", "--name", "EMU",
                    "--replay", "synthetic.jsonl", "--capture", "sensitive.jsonl", "a.pk3",
                ]
            )
        self.assertEqual(_arguments([
            "--game", "firered", "--trainer-id", "1", "--secret-id", "2", "--name", "EMU", "a.pk3"
        ]).keys, PROJECT_ROOT / ".switch" / "prod.keys")
        self.assertFalse(_arguments([
            "--game", "firered", "--trainer-id", "1", "--secret-id", "2",
            "--name", "EMU", "a.pk3",
        ]).disconnect_after_trade)

    def test_invalid_pk3_is_rejected_before_any_live_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.pk3"
            invalid.write_bytes(bytes(32) + b"\x01" + bytes(67))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "--game", "firered", "--trainer-id", "1", "--secret-id", "2", "--name", "EMU",
                    str(invalid),
                ]), 1)

    def test_verbose_diagnostics_exclude_identity_and_artifact_data(self) -> None:
        args = _arguments(
            [
                "--game", "firered", "--trainer-id", "12345", "--secret-id", "54321",
                "--name", "PRIVATE", "--verbose", "offered.pk3",
            ]
        )
        request = TradeRequest((PokemonArtifact("pk3", bytes(100), 3),))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _display_diagnostics(args, request)
        rendered = output.getvalue()
        self.assertIn("mode=live", rendered)
        self.assertIn("trades=1", rendered)
        self.assertNotIn("PRIVATE", rendered)
        self.assertNotIn("12345", rendered)
        self.assertNotIn("54321", rendered)
