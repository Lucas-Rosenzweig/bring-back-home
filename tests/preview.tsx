// Development-only visual harness. Not an entry point in the production build.
import React from "react";
import { createRoot } from "react-dom/client";
import App from "../src/App";
import { prepareCollection } from "../src/data/collection";
const ids = [
  1, 2, 3, 4, 5, 6, 7, 8, 9, 25, 26, 35, 37, 38, 39, 52, 54, 58, 59, 63, 65, 94,
  123, 129, 130, 131, 133, 134, 135, 136, 143, 147, 148, 149, 150, 151, 152,
  155, 158, 175, 196, 197, 249, 250, 251, 252, 255, 258, 282, 384, 448, 470,
  471, 700, 722, 744, 778, 810, 813, 816, 906, 909, 912, 1000, 1025,
];
const empty = new URLSearchParams(location.search).has("empty");
let trainer = new URLSearchParams(location.search).has("onboarding")
  ? null
  : { name: "Sacha", tid: 12345, sid: 54321 };
const service = {
  async loadCollection() {
    return {
      trainer,
      pokemon: prepareCollection(
        empty
          ? []
          : ids.map((id, i) => ({
              id: `fixture-${i}`,
              pk_format: 9,
              species_id: id,
              nickname: null,
              level: 15 + i,
              gender: i % 2 ? "female" : "male",
              is_shiny: i % 8 === 0 ? 1 : 0,
              origin_game: "Écarlate",
              created_at: i,
              storage_position: i,
              details_json: JSON.stringify({
                nature: "Modeste",
                ability: "Engrais",
                heldItem: "Aucun",
                ball: "Poké Ball",
                ivs: {
                  hp: 31,
                  attack: 12,
                  defense: 24,
                  specialAttack: 31,
                  specialDefense: 29,
                  speed: 31,
                },
                evs: {
                  hp: 4,
                  attack: 0,
                  defense: 0,
                  specialAttack: 252,
                  specialDefense: 0,
                  speed: 252,
                },
                moves: [
                  { name: "Vampigraine", type: "Plante", pp: 10, maxPp: 10 },
                ],
                originalTrainer: { name: "Sacha", tid: 12345, sid: 54321 },
              }),
            })),
      ),
    };
  },
  async createTrainer(name: string) {
    const ids = crypto.getRandomValues(new Uint16Array(2));
    trainer = { name: name.trim(), tid: ids[0], sid: ids[1] };
    return trainer;
  },
};
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App service={service} />
  </React.StrictMode>,
);
