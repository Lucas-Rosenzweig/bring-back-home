import speciesData from "./species.json";

export type Trainer = { name: string; tid: number; sid: number };
export const STAT_KEYS = [
  "hp",
  "attack",
  "defense",
  "specialAttack",
  "specialDefense",
  "speed",
] as const;
export type StatKey = (typeof STAT_KEYS)[number];
export type Stats = Partial<Record<StatKey, number>>;
export type Details = {
  form?: string;
  types?: string[];
  nature?: string;
  ability?: string;
  heldItem?: string;
  ivs?: Stats;
  evs?: Stats;
  stats?: Stats;
  moves?: { name: string; type?: string; pp?: number; maxPp?: number }[];
  originalTrainer?: { name?: string; tid?: number; sid?: number };
  metLocation?: string;
  metDate?: string;
  ball?: string;
};
export type PokemonRow = {
  id: string;
  pk_format: number;
  species_id: number;
  nickname: string | null;
  level: number;
  gender: string;
  is_shiny: number;
  origin_game: string | null;
  created_at: number;
  storage_position: number | null;
  details_json: string | null;
};
export type Pokemon = PokemonRow & {
  name: string;
  speciesName: string;
  types: string[];
  details: Details;
  position: number;
};
const species = speciesData as Record<
  string,
  { name: string; types: string[] }
>;
export const TYPE_NAMES = [
  "Normal",
  "Feu",
  "Eau",
  "Plante",
  "Électrik",
  "Glace",
  "Combat",
  "Poison",
  "Sol",
  "Vol",
  "Psy",
  "Insecte",
  "Roche",
  "Spectre",
  "Dragon",
  "Ténèbres",
  "Acier",
  "Fée",
];
export const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
export const typeClass = (type: string) => `type-${normalize(type)}`;
export const trainerId = (id: number) => id.toString().padStart(5, "0");

// Validate optional projections at the boundary; absent or malformed data is never invented.
export function parseDetails(raw: string | null): Details {
  if (!raw) return {};
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    const source = value as Record<string, unknown>;
    const result: Details = {};
    for (const key of [
      "form",
      "nature",
      "ability",
      "heldItem",
      "metLocation",
      "metDate",
      "ball",
    ] as const)
      if (typeof source[key] === "string") result[key] = source[key];
    if (
      Array.isArray(source.types) &&
      source.types.length &&
      source.types.every((t) => typeof t === "string" && TYPE_NAMES.includes(t))
    )
      result.types = source.types;
    for (const key of ["ivs", "evs", "stats"] as const) {
      const values = source[key];
      if (values && typeof values === "object") {
        const valid: Stats = {};
        for (const stat of STAT_KEYS) {
          const n = (values as Record<string, unknown>)[stat];
          if (
            typeof n === "number" &&
            Number.isInteger(n) &&
            n >= 0 &&
            n <= (key === "ivs" ? 31 : key === "evs" ? 255 : 9999)
          )
            valid[stat] = n;
        }
        result[key] = valid;
      }
    }
    if (Array.isArray(source.moves))
      result.moves = source.moves.slice(0, 4).flatMap((move) => {
        if (!move || typeof move.name !== "string") return [];
        return [
          {
            name: move.name,
            type: typeof move.type === "string" ? move.type : undefined,
            pp: Number.isInteger(move.pp) && move.pp >= 0 ? move.pp : undefined,
            maxPp:
              Number.isInteger(move.maxPp) && move.maxPp >= 0
                ? move.maxPp
                : undefined,
          },
        ];
      });
    if (source.originalTrainer && typeof source.originalTrainer === "object") {
      const ot = source.originalTrainer as Record<string, unknown>;
      result.originalTrainer = {
        name: typeof ot.name === "string" ? ot.name : undefined,
        tid:
          typeof ot.tid === "number" &&
          Number.isInteger(ot.tid) &&
          ot.tid >= 0 &&
          ot.tid <= 65535
            ? ot.tid
            : undefined,
        sid:
          typeof ot.sid === "number" &&
          Number.isInteger(ot.sid) &&
          ot.sid >= 0 &&
          ot.sid <= 65535
            ? ot.sid
            : undefined,
      };
    }
    return result;
  } catch {
    return {};
  }
}

export function prepareCollection(rows: PokemonRow[]): Pokemon[] {
  const occupied = new Set(
    rows.flatMap((r) =>
      r.storage_position === null ? [] : [r.storage_position],
    ),
  );
  let next = 0;
  return rows.map((row) => {
    while (occupied.has(next)) next++;
    const position = row.storage_position ?? next;
    occupied.add(position);
    const entry = species[row.species_id];
    const details = parseDetails(row.details_json);
    const speciesName = entry?.name ?? `Pokémon n° ${row.species_id}`;
    // Non-default forms may change type: don't assign default-form types to them.
    return {
      ...row,
      details,
      position,
      speciesName,
      name: row.nickname || speciesName,
      types: details.types ?? (details.form ? [] : (entry?.types ?? [])),
    };
  });
}

export type Filters = {
  query: string;
  type: string;
  shiny: boolean;
  generation: string;
  sort: string;
};
export function filterCollection(pokemon: Pokemon[], filters: Filters) {
  const query = normalize(filters.query.trim());
  return pokemon
    .filter(
      (p) =>
        (!query ||
          normalize(
            `${p.name} ${p.speciesName} ${p.species_id} ${p.origin_game ?? ""}`,
          ).includes(query)) &&
        (!filters.type || p.types.includes(filters.type)) &&
        (!filters.shiny || !!p.is_shiny) &&
        (!filters.generation || p.pk_format === Number(filters.generation)),
    )
    .sort((a, b) =>
      filters.sort === "dex"
        ? a.species_id - b.species_id || a.position - b.position
        : filters.sort === "level"
          ? b.level - a.level || a.position - b.position
          : filters.sort === "name"
            ? a.name.localeCompare(b.name, "fr") || a.position - b.position
            : a.position - b.position,
    );
}
