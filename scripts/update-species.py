"""Refresh the bundled French default-form species catalog from PokeAPI."""
import csv
import io
import json
import pathlib
import urllib.request

BASE = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
ROOT = pathlib.Path(__file__).resolve().parents[1]

def rows(filename):
    with urllib.request.urlopen(BASE + filename, timeout=30) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode())))

names = {int(r['pokemon_species_id']): r['name'] for r in rows('pokemon_species_names.csv') if r['local_language_id'] == '5'}
types = {int(r['type_id']): r['name'] for r in rows('type_names.csv') if r['local_language_id'] == '5'}
pokemon_types = {}
for row in rows('pokemon_types.csv'):
    pokemon_types.setdefault(int(row['pokemon_id']), []).append(types[int(row['type_id'])])
catalog = {r['species_id']: {'name': names.get(int(r['species_id']), r['identifier']), 'types': pokemon_types.get(int(r['id']), [])} for r in rows('pokemon.csv') if r['is_default'] == '1'}
(ROOT / 'src/data/species.json').write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')) + '\n')
print(f'{len(catalog)} espèces mises à jour.')
