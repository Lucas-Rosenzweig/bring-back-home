"""Reversible local fixtures. Snapshots are complete SQLite databases, never file copies."""
import argparse
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COUNT = 960


def default_database():
    config = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())
    identifier = config['identifier']
    # tauri-plugin-sql resolves SQLite paths relative to app_config_dir.
    if sys.platform == 'darwin':
        directory = Path.home() / 'Library/Application Support'
    elif sys.platform == 'win32':
        if not os.environ.get('APPDATA'):
            raise RuntimeError('APPDATA indisponible : précisez --db.')
        directory = Path(os.environ['APPDATA'])
    else:
        directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    url, = config['plugins']['sql']['preload']
    if not url.startswith('sqlite:'):
        raise RuntimeError('La base configurée doit être SQLite.')
    return directory / identifier / url.removeprefix('sqlite:')


def backup_path(path):
    return path.with_name(path.name + '.fixtures-original.sqlite3')


def connect(path, readonly=False):
    # URI mode=rw fails instead of creating a new database at a mistaken path.
    return sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=5)


def verify(db):
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise RuntimeError('La vérification SQLite a échoué. Aucune sauvegarde ne sera supprimée.')


def snapshot(source, destination):
    deadline = time.monotonic() + 10
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise RuntimeError('SQLite est occupée. Fermez Tauri et réessayez.')
    source.backup(destination, pages=256, progress=progress, sleep=0.05)
    verify(destination)


def ensure_closed(path):
    # SQLite's backup/transactions remain authoritative for consistency. This
    # additional guard prevents replacing data under an already running UI.
    lsof = shutil.which('lsof')
    if not lsof and sys.platform != 'win32' and Path('/usr/sbin/lsof').exists():
        lsof = '/usr/sbin/lsof'
    if lsof:
        files = [str(p) for p in [path, Path(str(path) + '-wal'), Path(str(path) + '-shm')] if p.exists()]
        result = subprocess.run([lsof, '-t', '--', *files], capture_output=True, text=True, timeout=10)
        if result.returncode not in (0, 1):
            raise RuntimeError('Impossible de vérifier les processus utilisant la base avec lsof.')
        if result.stdout.strip():
            raise RuntimeError('La base est ouverte par une application. Fermez la fenêtre Tauri avant de basculer les fixtures.')
    elif sys.platform == 'win32':
        # Windows: sharing mode zero refuses any already open database handle.
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0x80000000, 0, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise RuntimeError('Impossible de verrouiller la base. Fermez Tauri et vérifiez vos permissions.')
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(handle)
    else:
        raise RuntimeError('Installez lsof pour vérifier que Tauri est fermé avant de basculer les fixtures.')


@contextmanager
def operation_lock(path):
    lock = path.with_name(path.name + '.fixtures-lock')
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise RuntimeError(f'Une opération fixtures est déjà en cours. Si elle a été interrompue, vérifiez qu’aucune commande ne tourne puis retirez le dossier {lock}.') from None
    try:
        yield
    finally:
        lock.rmdir()


def fixture_rows(count):
    catalog = json.loads((ROOT / 'src/data/species.json').read_text())
    rng = random.Random(20260914)
    keys = ['hp', 'attack', 'defense', 'specialAttack', 'specialDefense', 'speed']
    maxima = [386, 493, 649, 721, 809, 905, 1025]
    games = ['Émeraude', 'Platine', 'Noir 2', 'X', 'Ultra-Soleil', 'Épée', 'Écarlate']
    natures = ['Hardi', 'Timide', 'Modeste', 'Rigide', 'Calme', 'Jovial']
    for i in range(count):
        generation = i % 7
        species = (i * 17) % maxima[generation] + 1
        ivs = dict.fromkeys(keys, 31) if i % 10 == 0 else {key: rng.randrange(32) for key in keys}
        evs = dict.fromkeys(keys, 0)
        if i % 3:
            evs.update(hp=4, attack=252, speed=252)
        details = {
            'types': catalog[str(species)]['types'],
            'nature': natures[i % len(natures)],
            'heldItem': 'Aucun' if i % 2 else 'Baie Oran',
            'ivs': ivs, 'evs': evs,
            'stats': {key: rng.randrange(30, 301) for key in keys},
            'moves': [{'name': 'Charge', 'type': 'Normal', 'pp': 20, 'maxPp': 35},
                      {'name': 'Abri', 'type': 'Normal', 'pp': 10, 'maxPp': 10}],
            'originalTrainer': {'name': 'Test HOME', 'tid': 12345, 'sid': 54321},
            'metLocation': 'Lieu de test', 'metDate': '2026-09-14', 'ball': 'Poké Ball',
        }
        # Intentionally NOT a valid .pk* file. Never export these as Pokémon.
        payload = b'BBH_FIXTURE_NOT_A_VALID_PK_FILE\x00' + str(i).encode('ascii')
        yield (f'fixture-{i:05d}', generation + 3, payload, species,
               f'Test {i + 1}' if i % 13 == 0 else None, i % 100 + 1,
               ['male', 'female', 'genderless', 'unknown'][i % 4], int(i % 9 == 0),
               games[generation], 1789344000 + i, 1789344000 + i, i,
               None if i % 19 == 18 else json.dumps(details, ensure_ascii=False))


def seed(db, count):
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('DELETE FROM pokemon')
        db.execute('DELETE FROM trainer')
        db.execute('INSERT INTO trainer (name, tid, sid) VALUES (?, ?, ?)', ('Test HOME', 12345, 54321))
        db.executemany('''INSERT INTO pokemon
            (id, pk_format, raw_data, species_id, nickname, level, gender, is_shiny,
             origin_game, created_at, updated_at, storage_position, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', fixture_rows(count))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def enable(path, count=DEFAULT_COUNT):
    if not 1 <= count <= 100000:
        raise RuntimeError('Le nombre de fixtures doit être compris entre 1 et 100 000.')
    original = backup_path(path)
    with operation_lock(path):
        if original.exists():
            raise RuntimeError(f'Une sauvegarde existe déjà : {original}. Lancez disable avant une nouvelle activation ; elle ne sera pas écrasée.')
        ensure_closed(path)
        with closing(connect(path)) as db:
            verify(db)
            # Fail before backing up or deleting anything if migrations are missing.
            db.execute('SELECT storage_position, details_json FROM pokemon LIMIT 0')
            db.execute('SELECT name, tid, sid FROM trainer LIMIT 0')
            temporary = original.with_name(original.name + '.pending')
            if temporary.exists():
                raise RuntimeError(f'Sauvegarde interrompue détectée : {temporary}. Conservez-la et vérifiez-la avant de reprendre.')
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            try:
                with closing(sqlite3.connect(temporary)) as target:
                    snapshot(db, target)
                    # Keep the saved snapshot standalone even when the source uses WAL.
                    target.execute('PRAGMA journal_mode=DELETE')
                with temporary.open('rb') as file:
                    os.fsync(file.fileno())
                # Publish without replacing any pre-existing original snapshot.
                os.link(temporary, original)
                temporary.unlink()
                if os.name == 'posix':
                    directory = os.open(original.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except BaseException:
                # Retain incomplete artifacts for recovery, never seed on failure.
                raise
            # The full recoverable snapshot exists before the first DELETE.
            seed(db, count)
    return original


def disable(path):
    original = backup_path(path)
    with operation_lock(path):
        if not original.exists():
            raise RuntimeError('Aucune sauvegarde fixtures à restaurer. La base reste inchangée.')
        ensure_closed(path)
        with closing(connect(original, readonly=True)) as source:
            verify(source)
            source.execute('SELECT name, tid, sid FROM trainer LIMIT 0')
            source.execute('SELECT id FROM pokemon LIMIT 0')
            with closing(connect(path)) as target:
                snapshot(source, target)
        # Removed only after successful, validated restoration and closed handles.
        original.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['enable', 'disable', 'status'])
    parser.add_argument('--db', type=Path, help='Base alternative, notamment pour les tests isolés')
    parser.add_argument('--count', type=int, default=None, help='Nombre de Pokémon factices (enable uniquement, défaut : 960)')
    args = parser.parse_args()
    if args.count is not None and args.action != 'enable':
        parser.error('--count est réservé à enable')
    try:
        path = (args.db or default_database()).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f'Base introuvable : {path}. Lancez d’abord Tauri pour initialiser la base, puis fermez sa fenêtre.')
        if args.action == 'enable':
            count = args.count if args.count is not None else DEFAULT_COUNT
            original = enable(path, count)
            print(f'Fixtures activées : {count} Pokémon factices, {(count + 29) // 30} boîtes et le dresseur Test HOME.\nSauvegarde : {original}\nVous pouvez relancer Tauri. Pour restaurer : npm test disable')
        elif args.action == 'disable':
            disable(path)
            print(f'Base d’origine restaurée : {path}\nVous pouvez relancer Tauri.')
        else:
            print(f'Base : {path}\nSauvegarde : {backup_path(path)}\nÉtat : ' + ('sauvegarde présente, restauration disponible' if backup_path(path).exists() else 'aucune sauvegarde fixtures'))
    except (RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f'Fixtures : {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
