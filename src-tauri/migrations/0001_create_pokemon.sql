-- Pokémon PK* collection schema (.pk3 through .pk9).
CREATE TABLE IF NOT EXISTS pokemon (
  id TEXT PRIMARY KEY NOT NULL,
  pk_format INTEGER NOT NULL CHECK (pk_format BETWEEN 3 AND 9),
  raw_data BLOB NOT NULL CHECK (typeof(raw_data) = 'blob'),
  species_id INTEGER NOT NULL CHECK (species_id > 0),
  nickname TEXT,
  level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 100),
  gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'genderless', 'unknown')),
  is_shiny INTEGER NOT NULL CHECK (is_shiny IN (0, 1)),
  origin_game TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pokemon_species_id ON pokemon (species_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_pk_format ON pokemon (pk_format);
CREATE INDEX IF NOT EXISTS idx_pokemon_is_shiny ON pokemon (is_shiny);
CREATE INDEX IF NOT EXISTS idx_pokemon_origin_game ON pokemon (origin_game);
