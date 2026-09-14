import pathlib
import sqlite3
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CollectionMigrationTest(unittest.TestCase):
    def test_migration_preserves_payloads_and_trainer_and_assigns_positions(self):
        db = sqlite3.connect(':memory:')
        for version in ['0001_create_pokemon.sql', '0002_create_trainer.sql']:
            db.executescript((ROOT / 'src-tauri/migrations' / version).read_text())
        for i in range(65):
            db.execute('INSERT INTO pokemon VALUES (?,9,?,25,NULL,50,"male",0,NULL,?,?)', (str(i), bytes([i, 0, 255]), i, i))
        db.execute('INSERT INTO trainer VALUES ("Sacha",0,65535)')
        before = db.execute('SELECT id, raw_data FROM pokemon ORDER BY id').fetchall()
        db.executescript((ROOT / 'src-tauri/migrations/0003_collection_details.sql').read_text())
        self.assertEqual(before, db.execute('SELECT id, raw_data FROM pokemon ORDER BY id').fetchall())
        self.assertEqual(list(range(65)), [r[0] for r in db.execute('SELECT storage_position FROM pokemon ORDER BY created_at')])
        self.assertEqual(('Sacha', 0, 65535), db.execute('SELECT * FROM trainer').fetchone())
        with self.assertRaises(sqlite3.IntegrityError): db.execute('INSERT INTO trainer VALUES ("Other",1,2)')
        with self.assertRaises(sqlite3.IntegrityError): db.execute('UPDATE pokemon SET storage_position = 0 WHERE id = "1"')
        with self.assertRaises(sqlite3.IntegrityError): db.execute('UPDATE pokemon SET details_json = "invalid" WHERE id = "0"')

    def test_new_database_can_create_one_profile(self):
        db = sqlite3.connect(':memory:')
        for migration in sorted((ROOT / 'src-tauri/migrations').glob('*.sql')): db.executescript(migration.read_text())
        db.execute('INSERT INTO trainer VALUES (?,?,?)', ('Élise', 12345, 54321))
        self.assertEqual(('Élise', 12345, 54321), db.execute('SELECT * FROM trainer').fetchone())
        with self.assertRaises(sqlite3.IntegrityError): db.execute('INSERT INTO trainer VALUES ("Second",2,3)')

if __name__ == '__main__': unittest.main()
