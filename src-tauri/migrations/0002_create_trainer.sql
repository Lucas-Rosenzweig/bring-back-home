-- Trainer identity used by Pokémon PK* files.
CREATE TABLE IF NOT EXISTS trainer (
  name TEXT NOT NULL,
  tid INTEGER NOT NULL CHECK (tid BETWEEN 0 AND 65535),
  sid INTEGER NOT NULL CHECK (sid BETWEEN 0 AND 65535)
);
