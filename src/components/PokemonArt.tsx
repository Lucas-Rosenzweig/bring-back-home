import { useState } from "react";
import type { Pokemon } from "../data/collection";
import { Ball } from "./Icon";

export function PokemonArt({
  pokemon,
  large = false,
}: {
  pokemon: Pokemon;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  // A form-specific asset must be resolved by the future PK* decoder.
  if (failed || pokemon.details.form)
    return (
      <span
        className={`art-fallback ${large ? "large" : ""}`}
        title="Illustration indisponible"
      >
        <Ball />
      </span>
    );
  const folder = large ? "other/official-artwork/" : "";
  return (
    <img
      className={`pokemon-art ${large ? "large" : ""}`}
      src={`https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${folder}${pokemon.is_shiny ? "shiny/" : ""}${pokemon.species_id}.png`}
      alt=""
      loading={large ? "eager" : "lazy"}
      onError={() => setFailed(true)}
      draggable={false}
    />
  );
}
