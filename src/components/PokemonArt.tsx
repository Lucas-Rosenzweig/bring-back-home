import { useState } from "react";
import type { Pokemon } from "../data/collection";
import { Ball } from "./Icon";

const ONLINE_ASSETS =
  "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon";

function Placeholder({ large }: { large: boolean }) {
  return (
    <span
      className={`art-fallback ${large ? "large" : ""}`}
      title="Illustration indisponible"
    >
      <Ball />
    </span>
  );
}

// Keyed by asset path so changing Pokémon, shiny state or image size starts
// a fresh local-first attempt, even when the previous asset failed.
function LocalFirstImage({ path, large }: { path: string; large: boolean }) {
  const [attempt, setAttempt] = useState(0);
  if (attempt >= 2) return <Placeholder large={large} />;

  const src =
    attempt === 0 ? `/assets/pokemon/${path}` : `${ONLINE_ASSETS}/${path}`;

  return (
    <img
      className={`pokemon-art ${large ? "large" : ""}`}
      src={src}
      alt=""
      loading={large ? "eager" : "lazy"}
      onError={() => setAttempt(attempt + 1)}
      draggable={false}
    />
  );
}

export function PokemonArt({
  pokemon,
  large = false,
}: {
  pokemon: Pokemon;
  large?: boolean;
}) {
  // A textual form name cannot identify its sprite reliably. The downloaded
  // alternate-form assets are ready for the future decoder's form mapping.
  if (pokemon.details.form) return <Placeholder large={large} />;
  const folder = large ? "other/official-artwork/" : "";
  const path = `${folder}${pokemon.is_shiny ? "shiny/" : ""}${pokemon.species_id}.png`;
  return <LocalFirstImage key={path} path={path} large={large} />;
}
