import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'scripts/fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class FixturesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'collection.db'
        with sqlite3.connect(self.path) as db:
            for migration in sorted((ROOT / 'src-tauri/migrations').glob('*.sql')):
                db.executescript(migration.read_text())
            db.execute('INSERT INTO trainer VALUES (?,?,?)', ('Élise', 0, 65535))
            db.execute('''INSERT INTO pokemon
                (id,pk_format,raw_data,species_id,level,gender,is_shiny,created_at,updated_at,storage_position)
                VALUES ('original',3,?,25,42,'female',1,123,456,41)''', (b'\x00\x01\xfforiginal',))
            db.execute('CREATE TABLE migration_metadata (version INTEGER, checksum BLOB)')
            db.execute('INSERT INTO migration_metadata VALUES (3, ?)', (b'\x00\xff',))
        db.close()
        self.before = self.dump(self.path)

    def dump(self, path):
        with fixtures.closing(fixtures.connect(path, readonly=True)) as db:
            return '\n'.join(db.iterdump())

    def enable(self, count=fixtures.DEFAULT_COUNT):
        # Unit tests isolate the database operations from OS process discovery.
        with patch.object(fixtures, 'ensure_closed'):
            return fixtures.enable(self.path, count)

    def disable(self):
        with patch.object(fixtures, 'ensure_closed'):
            fixtures.disable(self.path)

    def test_full_round_trip_restores_all_tables_blobs_and_positions(self):
        original = self.enable()
        self.assertEqual(self.dump(original), self.before)
        with fixtures.closing(fixtures.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pokemon').fetchone()[0], 960)
            self.assertEqual(db.execute('SELECT * FROM trainer').fetchone(), ('Test HOME', 12345, 54321))
            self.assertEqual(db.execute('SELECT count(DISTINCT pk_format) FROM pokemon').fetchone()[0], 7)
            self.assertEqual(db.execute('SELECT max(storage_position) FROM pokemon').fetchone()[0], 959)
            self.assertEqual(db.execute('SELECT count(*) FROM pokemon WHERE details_json IS NULL').fetchone()[0], 50)
            self.assertTrue(db.execute('SELECT raw_data FROM pokemon LIMIT 1').fetchone()[0].startswith(b'BBH_FIXTURE_NOT_A_VALID_PK_FILE'))
            # Simulate test-time changes, including tables absent from the original.
            db.execute('CREATE TABLE test_only (value TEXT)')
            db.execute('UPDATE trainer SET name = "Modified"')
            db.commit()
        self.disable()
        self.assertEqual(self.dump(self.path), self.before)
        self.assertFalse(original.exists())

    def test_repeated_enable_never_overwrites_original(self):
        original = self.enable(60)
        backup_bytes = original.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'sauvegarde existe déjà'):
            self.enable(90)
        self.assertEqual(original.read_bytes(), backup_bytes)
        self.disable()
        self.assertEqual(self.dump(self.path), self.before)

    def test_disable_without_snapshot_and_invalid_count_do_not_change_database(self):
        with self.assertRaisesRegex(RuntimeError, 'Aucune sauvegarde'):
            self.disable()
        with self.assertRaises(RuntimeError):
            self.enable(0)
        self.assertEqual(self.dump(self.path), self.before)
        self.assertFalse(fixtures.backup_path(self.path).exists())

    def test_seed_failure_rolls_back_and_keeps_recovery_snapshot(self):
        first_row = next(fixtures.fixture_rows(1))
        with patch.object(fixtures, 'fixture_rows', return_value=iter([first_row, ('invalid',)])):
            with self.assertRaises(sqlite3.ProgrammingError):
                self.enable()
        self.assertEqual(self.dump(self.path), self.before)
        self.assertTrue(fixtures.backup_path(self.path).exists())
        self.disable()
        self.assertEqual(self.dump(self.path), self.before)

    def test_corrupt_snapshot_does_not_touch_current_database(self):
        original = self.enable(60)
        current = self.dump(self.path)
        original.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.disable()
        self.assertEqual(self.dump(self.path), current)
        self.assertTrue(original.exists())

    def test_busy_app_is_rejected_before_backup_or_deletion(self):
        with patch.object(fixtures, 'ensure_closed', side_effect=RuntimeError('Fermez Tauri')):
            with self.assertRaisesRegex(RuntimeError, 'Fermez Tauri'):
                fixtures.enable(self.path)
        self.assertEqual(self.dump(self.path), self.before)
        self.assertFalse(fixtures.backup_path(self.path).exists())

    def test_snapshot_includes_committed_wal_contents(self):
        with fixtures.closing(fixtures.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('UPDATE trainer SET name="WAL original"')
            db.commit()
            self.assertTrue(Path(str(self.path) + '-wal').exists())
            original = self.enable(30)
            with fixtures.closing(fixtures.connect(original, readonly=True)) as saved:
                self.assertEqual(saved.execute('SELECT name FROM trainer').fetchone()[0], 'WAL original')
        self.disable()
        with fixtures.closing(fixtures.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT name FROM trainer').fetchone()[0], 'WAL original')

    def test_open_database_handle_is_detected(self):
        with fixtures.closing(fixtures.connect(self.path)) as db:
            db.execute('SELECT * FROM trainer').fetchall()
            with self.assertRaisesRegex(RuntimeError, 'Fermez|Installez lsof'):
                fixtures.ensure_closed(self.path)

    def test_operation_lock_blocks_parallel_activation(self):
        with fixtures.operation_lock(self.path):
            with self.assertRaisesRegex(RuntimeError, 'déjà en cours'):
                self.enable()
        self.assertEqual(self.dump(self.path), self.before)


if __name__ == '__main__':
    unittest.main()
