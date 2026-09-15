"""Bundle PokeAPI sprites/artwork (normal, shiny, female and alternate forms).

Run: python3 scripts/download-pokemon-assets.py
Verify the complete local bundle without network: add --verify.
Only the image families used by the application are downloaded, not duplicate
assets from every historical game, animated sprites or unrelated item icons.
"""
import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'public/assets/pokemon'
MANIFEST = DEST / 'manifest.json'
API = 'https://api.github.com/repos/PokeAPI/sprites'
RAW = 'https://raw.githubusercontent.com/PokeAPI/sprites'
FOLDERS = ['', 'shiny', 'female', 'shiny/female', 'other/official-artwork', 'other/official-artwork/shiny']


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BringBackHome-asset-downloader'})
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def valid(entry):
    path = DEST / entry['path']
    return path.is_file() and path.stat().st_size == entry['size'] and blob_sha(path.read_bytes()) == entry['sha']


def inventory():
    revision = json.loads(get(API + '/commits/master'))['sha']
    cache = {}

    def tree(path):
        if path not in cache:
            if not path:
                sha = revision
            else:
                parent, _, name = path.rpartition('/')
                sha = next(item['sha'] for item in tree(parent) if item['path'] == name and item['type'] == 'tree')
            cache[path] = json.loads(get(API + '/git/trees/' + sha))['tree']
        return cache[path]

    files = []
    for folder in FOLDERS:
        directory = 'sprites/pokemon' + ('/' + folder if folder else '')
        for item in tree(directory):
            if item['type'] == 'blob' and item['path'].endswith('.png'):
                files.append({'path': (folder + '/' if folder else '') + item['path'], 'sha': item['sha'], 'size': item['size']})
    return {'source': 'https://github.com/PokeAPI/sprites', 'revision': revision, 'folders': FOLDERS, 'files': sorted(files, key=lambda x: x['path'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Verify local checksums without network access')
    parser.add_argument('--update', action='store_true', help='Refresh the pinned upstream inventory')
    args = parser.parse_args()
    if args.verify:
        if not MANIFEST.exists():
            raise SystemExit('Missing asset manifest. Run the downloader first.')
        manifest = json.loads(MANIFEST.read_text())
        broken = [entry['path'] for entry in manifest['files'] if not valid(entry)]
        if broken:
            raise SystemExit('Missing or corrupted assets:\n' + '\n'.join(broken))
        print(f"Verified {len(manifest['files'])} PNG files, offline.")
        return
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() and not args.update else inventory()
    DEST.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    entries = manifest['files']
    print(f"Downloading/verifying {len(entries)} files at {manifest['revision']} ({sum(e['size'] for e in entries) / 1024**2:.1f} MiB)", flush=True)

    def download(entry):
        if valid(entry):
            return
        data = get(f"{RAW}/{manifest['revision']}/sprites/pokemon/{entry['path']}")
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or blob_sha(data) != entry['sha']:
            raise ValueError(f"Invalid image: {entry['path']}")
        target = DEST / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.png.part')
        temporary.write_bytes(data)
        temporary.replace(target)

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        jobs = {pool.submit(download, entry): entry['path'] for entry in entries}
        for i, future in enumerate(concurrent.futures.as_completed(jobs), 1):
            try:
                future.result()
            except Exception as error:
                failures.append((jobs[future], str(error)))
            if i % 200 == 0 or i == len(entries):
                print(f'{i}/{len(entries)} checked ({len(failures)} errors)', flush=True)
    if failures:
        raise SystemExit('Rerun to resume failed downloads:\n' + '\n'.join(f'{p}: {e}' for p, e in failures))
    print('Complete. All assets verified against their upstream Git blob SHA.', flush=True)


if __name__ == '__main__':
    main()
