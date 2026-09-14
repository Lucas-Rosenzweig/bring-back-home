import Database from "@tauri-apps/plugin-sql";
import { isTauri } from "@tauri-apps/api/core";
import { prepareCollection, type PokemonRow, type Trainer } from "./collection";

let connection: Promise<Database> | undefined;
function database() {
  if (!isTauri())
    throw new Error(
      "Ouvrez Bring Back Home dans l’application desktop pour accéder à votre collection locale.",
    );
  return (connection ??= Database.load("sqlite:bring-back-home.db").catch(
    (error) => {
      connection = undefined;
      throw error;
    },
  ));
}
export async function loadCollection() {
  const db = await database();
  const [trainers, rows] = await Promise.all([
    db.select<Trainer[]>(
      "SELECT name, tid, sid FROM trainer ORDER BY rowid LIMIT 1",
    ),
    db.select<PokemonRow[]>(
      "SELECT id, pk_format, species_id, nickname, level, gender, is_shiny, origin_game, created_at, storage_position, details_json FROM pokemon ORDER BY created_at, id",
    ),
  ]);
  return { trainer: trainers[0] ?? null, pokemon: prepareCollection(rows) };
}
export async function createTrainer(name: string): Promise<Trainer> {
  const trimmed = name.trim();
  if (
    !trimmed ||
    Array.from(trimmed).length > 12 ||
    /[\u0000-\u001f\u007f]/u.test(trimmed)
  )
    throw new Error(
      "Choisissez un nom de 1 à 12 caractères, sans caractère de contrôle.",
    );
  const db = await database();
  const ids = crypto.getRandomValues(new Uint16Array(2));
  const trainer = { name: trimmed, tid: ids[0], sid: ids[1] };
  // A trigger enforces the singleton even if two requests race.
  await db.execute("INSERT INTO trainer (name, tid, sid) VALUES ($1, $2, $3)", [
    trainer.name,
    trainer.tid,
    trainer.sid,
  ]);
  return trainer;
}
