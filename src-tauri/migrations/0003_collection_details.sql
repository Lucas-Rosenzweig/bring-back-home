-- Stable, zero-based positions for existing records. PK* payloads are untouched.
ALTER TABLE pokemon ADD COLUMN storage_position INTEGER CHECK (storage_position >= 0);
ALTER TABLE pokemon ADD COLUMN details_json TEXT CHECK (details_json IS NULL OR json_valid(details_json));
WITH ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) - 1 AS position FROM pokemon
)
UPDATE pokemon SET storage_position = (SELECT position FROM ranked WHERE ranked.id = pokemon.id);
CREATE UNIQUE INDEX idx_pokemon_storage_position ON pokemon(storage_position);
-- Guard the single local profile without deleting any existing identity.
CREATE TRIGGER trainer_single_profile BEFORE INSERT ON trainer
WHEN EXISTS (SELECT 1 FROM trainer)
BEGIN SELECT RAISE(ABORT, 'Un profil local existe déjà.'); END;
