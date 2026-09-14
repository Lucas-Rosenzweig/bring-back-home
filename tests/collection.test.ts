import { test } from "node:test";
import assert from "node:assert/strict";
import {
  filterCollection,
  parseDetails,
  prepareCollection,
  trainerId,
  type PokemonRow,
} from "../src/data/collection";
const row = (
  id: string,
  position: number | null,
  changes: Partial<PokemonRow> = {},
): PokemonRow => ({
  id,
  storage_position: position,
  species_id: 133,
  pk_format: 9,
  nickname: null,
  gender: "unknown",
  is_shiny: 0,
  level: 20,
  origin_game: null,
  created_at: 0,
  details_json: null,
  ...changes,
});
const filters = {
  query: "",
  type: "",
  shiny: false,
  generation: "",
  sort: "position",
};
test("positions preserve gaps and place unassigned records without collisions", () => {
  const data = prepareCollection([
    row("a", 0),
    row("b", 30),
    row("c", null),
    row("d", null),
  ]);
  assert.deepEqual(
    data.map((p) => p.position),
    [0, 30, 1, 2],
  );
});
test("search is accent-insensitive and filters combine across boxes", () => {
  const data = prepareCollection([
    row("a", 0),
    row("b", 31, {
      nickname: "Éclair",
      species_id: 25,
      is_shiny: 1,
      level: 50,
    }),
  ]);
  assert.equal(
    filterCollection(data, {
      ...filters,
      query: "eclair",
      type: "Électrik",
      shiny: true,
      generation: "9",
    })[0]?.id,
    "b",
  );
  assert.equal(
    filterCollection(data, { ...filters, query: "evoli" })[0]?.id,
    "a",
  );
  assert.equal(
    filterCollection(data, { ...filters, shiny: true, generation: "3" }).length,
    0,
  );
  assert.deepEqual(
    filterCollection(data, { ...filters, sort: "level" }).map((p) => p.id),
    ["b", "a"],
  );
});
test("missing metadata remains unknown and malformed projections do not crash", () => {
  for (const raw of [null, "null", "[]", "42", "{broken"])
    assert.deepEqual(parseDetails(raw), {});
  const details = parseDetails(
    JSON.stringify({
      ivs: { hp: 0, attack: 31, speed: 32 },
      evs: { hp: 0, attack: -1 },
      nature: {},
      moves: [null, 1, { name: "Charge", pp: -2 }],
      originalTrainer: { tid: 65536 },
    }),
  );
  assert.deepEqual(details.ivs, { hp: 0, attack: 31 });
  assert.deepEqual(details.evs, { hp: 0 });
  assert.equal(details.moves?.length, 1);
  assert.equal(details.moves?.[0].pp, undefined);
  assert.equal(details.originalTrainer?.tid, undefined);
});
test("alternative forms do not inherit potentially incorrect default types", () => {
  assert.deepEqual(
    prepareCollection([row("a", 0, { details_json: '{"form":"Alola"}' })])[0]
      .types,
    [],
  );
  assert.deepEqual(
    prepareCollection([
      row("a", 0, { details_json: '{"form":"Alola","types":["Glace"]}' }),
    ])[0].types,
    ["Glace"],
  );
});
test("trainer IDs retain leading zeros including zero", () => {
  assert.equal(trainerId(0), "00000");
  assert.equal(trainerId(65535), "65535");
});
