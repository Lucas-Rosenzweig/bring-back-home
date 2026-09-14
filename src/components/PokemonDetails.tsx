import { useEffect, useRef, useState } from "react";
import {
  STAT_KEYS,
  trainerId,
  typeClass,
  type Pokemon,
} from "../data/collection";
import { Icon } from "./Icon";
import { PokemonArt } from "./PokemonArt";

const labels = [
  "PV",
  "Attaque",
  "Défense",
  "Att. Spé.",
  "Déf. Spé.",
  "Vitesse",
];
export function TypeBadge({ type }: { type: string }) {
  return <span className={`type-badge ${typeClass(type)}`}>{type}</span>;
}
export function PokemonDetails({
  pokemon: p,
  onClose,
}: {
  pokemon: Pokemon;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("summary");
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
  }, []);
  const d = p.details;
  return (
    <aside
      className="detail-panel"
      aria-label={`Détails de ${p.name}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="detail-top">
        <span className="eyebrow">FICHE POKÉMON</span>
        <button
          ref={closeButton}
          className="icon-button"
          aria-label="Fermer la fiche"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="pokemon-stage">
        <div className="stage-orbit" />
        <BallWatermark />
        <PokemonArt key={p.id} pokemon={p} large />
        {!!p.is_shiny && (
          <span className="shiny-label">
            <Icon name="sparkles" size={14} /> Chromatique
          </span>
        )}
      </div>
      <div className="pokemon-identity">
        <span className="eyebrow">
          N° {String(p.species_id).padStart(4, "0")} · {p.speciesName}
        </span>
        <h2>
          {p.name}{" "}
          <span className={`gender ${p.gender}`}>
            {p.gender === "male" ? "♂" : p.gender === "female" ? "♀" : ""}
          </span>
        </h2>
        <div className="identity-meta">
          <div className="type-list">
            {p.types.map((t) => (
              <TypeBadge key={t} type={t} />
            ))}
          </div>
          <span>
            Niv. <strong>{p.level}</strong>
          </span>
        </div>
        {d.form && <p className="muted">{d.form}</p>}
      </div>
      <div
        className="detail-tabs"
        role="tablist"
        aria-label="Informations du Pokémon"
      >
        {[
          ["summary", "Résumé"],
          ["stats", "IV / EV"],
          ["moves", "Capacités"],
        ].map(([value, label], index, items) => (
          <button
            key={value}
            id={`tab-${value}`}
            role="tab"
            aria-selected={tab === value}
            aria-controls="detail-content"
            tabIndex={tab === value ? 0 : -1}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                e.preventDefault();
                const next =
                  items[(index + (e.key === "ArrowRight" ? 1 : 2)) % 3][0];
                setTab(next);
                document.getElementById(`tab-${next}`)?.focus();
              }
            }}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        className="detail-content"
        id="detail-content"
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        tabIndex={0}
      >
        {tab === "summary" && (
          <>
            <dl className="info-list">
              {[
                ["Nature", d.nature],
                ["Talent", d.ability],
                ["Objet tenu", d.heldItem],
                ["Jeu d’origine", p.origin_game],
                ["Poké Ball", d.ball],
                ["Lieu de rencontre", d.metLocation],
                ["Date de rencontre", d.metDate],
              ].map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value || "Non renseigné"}</dd>
                </div>
              ))}
            </dl>
            <h3>Dresseur d’origine</h3>
            <div className="ot-card">
              <Icon name="user" />
              <div>
                <strong>{d.originalTrainer?.name ?? "Non renseigné"}</strong>
                <p>
                  TID{" "}
                  {d.originalTrainer?.tid === undefined
                    ? "—"
                    : trainerId(d.originalTrainer.tid)}{" "}
                  <span>·</span> SID{" "}
                  {d.originalTrainer?.sid === undefined
                    ? "—"
                    : trainerId(d.originalTrainer.sid)}
                </p>
              </div>
            </div>
          </>
        )}
        {tab === "stats" && (
          <>
            <div className="section-heading">
              <h3>Potentiel & entraînement</h3>
              <span className="small muted">IV / 31</span>
            </div>
            <table className="stat-table">
              <thead>
                <tr>
                  <th>Statistique</th>
                  <th>Valeur</th>
                  <th>IV</th>
                  <th>EV</th>
                </tr>
              </thead>
              <tbody>
                {STAT_KEYS.map((key, i) => (
                  <tr key={key}>
                    <th>
                      {labels[i]}
                      <span className="stat-track">
                        <span
                          style={{
                            width: `${((d.ivs?.[key] ?? 0) / 31) * 100}%`,
                          }}
                        />
                      </span>
                    </th>
                    <td>{d.stats?.[key] ?? "—"}</td>
                    <td className={d.ivs?.[key] === 31 ? "perfect" : ""}>
                      {d.ivs?.[key] ?? "—"}
                    </td>
                    <td>{d.evs?.[key] ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="data-note">
              Un tiret indique une donnée absente de la collection. Les
              statistiques ne sont pas déduites du niveau.
            </p>
          </>
        )}
        {tab === "moves" && (
          <>
            <h3>Capacités apprises</h3>
            <div className="moves-list">
              {Array.from({ length: 4 }, (_, i) => {
                const move = d.moves?.[i];
                return (
                  <div className="move" key={i}>
                    <span className="move-number">0{i + 1}</span>
                    <div>
                      <strong>{move?.name ?? "Non renseignée"}</strong>
                      {move?.type && <TypeBadge type={move.type} />}
                    </div>
                    <span className="muted small">
                      {move
                        ? `PP ${move.pp ?? "—"} / ${move.maxPp ?? "—"}`
                        : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
      <div className="detail-footer">
        <Icon name="box" size={15} /> Boîte{" "}
        {String(Math.floor(p.position / 30) + 1).padStart(2, "0")} · Emplacement{" "}
        {(p.position % 30) + 1}
        <span>PK{p.pk_format}</span>
      </div>
    </aside>
  );
}
function BallWatermark() {
  return (
    <div className="stage-ball" aria-hidden="true">
      <span />
    </div>
  );
}
