import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { PokemonArt } from "../src/components/PokemonArt";
import { prepareCollection } from "../src/data/collection";

test("Pokémon images use local assets, retry online only on failure, then show a Poké Ball", async () => {
  // jsdom doesn't load external resources: error events exercise the real
  // component without requiring the network or modifying the image bundle.
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost/" });
  const previous = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value,
    });
  }
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  const pokemon = prepareCollection([
    {
      id: "test",
      species_id: 25,
      pk_format: 9,
      nickname: null,
      level: 30,
      gender: "male",
      is_shiny: 0,
      origin_game: null,
      created_at: 0,
      storage_position: 0,
      details_json: null,
    },
  ])[0];
  const source = () => container.querySelector("img")?.getAttribute("src");
  const failImage = async () => {
    const image = container.querySelector("img");
    assert.ok(image);
    await act(async () => {
      image.dispatchEvent(new dom.window.Event("error"));
    });
  };
  try {
    await act(async () => root.render(<PokemonArt pokemon={pokemon} />));
    assert.equal(source(), "/assets/pokemon/25.png");
    await act(async () => {
      container
        .querySelector("img")!
        .dispatchEvent(new dom.window.Event("load"));
    });
    assert.equal(
      source(),
      "/assets/pokemon/25.png",
      "a local success must not request an online image",
    );
    await failImage();
    assert.equal(
      source(),
      "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/25.png",
    );
    await failImage();
    assert.equal(container.querySelector("img"), null);
    assert.ok(container.querySelector(".art-fallback .pokeball"));

    await act(async () =>
      root.render(<PokemonArt pokemon={{ ...pokemon, species_id: 133 }} />),
    );
    assert.equal(
      source(),
      "/assets/pokemon/133.png",
      "switching Pokémon resets a failed image",
    );
    await act(async () =>
      root.render(<PokemonArt pokemon={{ ...pokemon, is_shiny: 1 }} large />),
    );
    assert.equal(
      source(),
      "/assets/pokemon/other/official-artwork/shiny/25.png",
    );
    await failImage();
    assert.equal(
      source(),
      "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/25.png",
    );
    await failImage();
    assert.ok(container.querySelector(".art-fallback.large .pokeball"));

    await act(async () =>
      root.render(<PokemonArt pokemon={{ ...pokemon, is_shiny: 1 }} />),
    );
    assert.equal(
      source(),
      "/assets/pokemon/shiny/25.png",
      "changing size resets the asset attempt",
    );
    await act(async () =>
      root.render(
        <PokemonArt pokemon={{ ...pokemon, details: { form: "Inconnue" } }} />,
      ),
    );
    assert.equal(
      container.querySelector("img"),
      null,
      "do not substitute the default artwork for an unresolved form",
    );
    assert.ok(container.querySelector(".pokeball"));
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
