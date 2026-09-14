import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createTrainer, loadCollection } from "./data/database";
import {
  filterCollection,
  trainerId,
  TYPE_NAMES,
  type Filters,
  type Pokemon,
  type Trainer,
} from "./data/collection";
import { Ball, Icon } from "./components/Icon";
import { PokemonArt } from "./components/PokemonArt";
import { PokemonDetails } from "./components/PokemonDetails";
import "./App.css";

const DEFAULT_FILTERS: Filters = {
  query: "",
  type: "",
  shiny: false,
  generation: "",
  sort: "position",
};
const PAGE_SIZE = 60;

type CollectionService = {
  loadCollection: typeof loadCollection;
  createTrainer: typeof createTrainer;
};
const localService: CollectionService = { loadCollection, createTrainer };
function App({ service = localService }: { service?: CollectionService }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [trainer, setTrainer] = useState<Trainer | null>(null);
  const [pokemon, setPokemon] = useState<Pokemon[]>([]);
  const [view, setView] = useState<"boxes" | "all">("boxes");
  const [box, setBox] = useState(0);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedButton = useRef<HTMLButtonElement | null>(null);
  const [showProfile, setShowProfile] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await service.loadCollection();
      setTrainer(data.trainer);
      setPokemon(data.pokemon);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [service]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const boxCount = pokemon.reduce(
    (count, p) => Math.max(count, Math.floor(p.position / 30) + 1),
    1,
  );
  const positions = useMemo(
    () => new Map(pokemon.map((p) => [p.position, p])),
    [pokemon],
  );
  const filtered = useMemo(
    () => filterCollection(pokemon, filters),
    [pokemon, filters],
  );
  const current = pokemon.find((p) => p.id === selected);
  const shinyCount = pokemon.filter((p) => p.is_shiny).length;
  const speciesCount = new Set(pokemon.map((p) => p.species_id)).size;
  const boxPokemon = pokemon.filter((p) => Math.floor(p.position / 30) === box);
  const closeDetails = () => {
    setSelected(null);
    selectedButton.current?.focus();
  };
  const changeFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(0);
  };
  const switchView = (next: "boxes" | "all") => {
    setView(next);
    setPage(0);
  };

  if (loading || error)
    return (
      <main className="welcome-screen">
        <div className="welcome-card state-card">
          <Brand />
          <Ball className={loading ? "loading-ball" : ""} />
          <h1>
            {loading
              ? "Votre collection prend place…"
              : "Collection inaccessible"}
          </h1>
          <p>{loading ? "Ouverture de votre espace personnel." : error}</p>
          {error && (
            <button className="button primary" onClick={() => void refresh()}>
              <Icon name="refresh" /> Réessayer
            </button>
          )}
        </div>
      </main>
    );
  if (!trainer)
    return (
      <Onboarding
        onCreated={setTrainer}
        createProfile={service.createTrainer}
      />
    );

  return (
    <div className={`app-shell ${current ? "has-details" : ""}`}>
      <aside className="sidebar">
        <Brand />
        <div className="sidebar-section-label">VOTRE ESPACE</div>
        <nav aria-label="Navigation principale">
          <button
            className={`nav-item ${view === "boxes" ? "active" : ""}`}
            onClick={() => switchView("boxes")}
            aria-current={view === "boxes" ? "page" : undefined}
          >
            <Icon name="box" /> Mes boîtes <span>{boxCount}</span>
          </button>
          <button
            className={`nav-item ${view === "all" ? "active" : ""}`}
            onClick={() => switchView("all")}
            aria-current={view === "all" ? "page" : undefined}
          >
            <Icon name="grid" /> Tous les Pokémon
          </button>
        </nav>
        <div className="sidebar-collection">
          <span className="sidebar-section-label">LA COLLECTION</span>
          <div>
            <Ball />
            <strong>{pokemon.length.toLocaleString("fr-FR")}</strong>
            <span>Pokémon à la maison</span>
          </div>
          <div className="collection-line">
            <span>Espèces différentes</span>
            <strong>{speciesCount}</strong>
          </div>
          <div className="collection-line">
            <span>
              <Icon name="sparkles" size={14} /> Chromatiques
            </span>
            <strong>{shinyCount}</strong>
          </div>
        </div>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span /> Collection locale
          </div>
          <button
            className="profile-button"
            onClick={() => setShowProfile(true)}
          >
            <span className="avatar">
              {Array.from(trainer.name)[0].toLocaleUpperCase("fr-FR")}
            </span>
            <span>
              <strong>{trainer.name}</strong>
              <small>TID {trainerId(trainer.tid)}</small>
            </span>
            <Icon name="chevron-right" size={16} />
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <div className="breadcrumb">
            Votre espace <span>/</span>{" "}
            <strong>
              {view === "boxes" ? "Mes boîtes" : "Tous les Pokémon"}
            </strong>
          </div>
          <span className="read-only">
            <span /> Consultation
          </span>
        </header>
        <div className="workspace-body">
          <div className="page-heading">
            <div>
              <div className="eyebrow">CHAQUE POKÉMON A SA PLACE</div>
              <h1>
                {view === "boxes"
                  ? "Bienvenue à la maison."
                  : "Toute votre collection."}
              </h1>
              <p>
                {view === "boxes"
                  ? "Vos compagnons, réunis dans un seul endroit."
                  : "Retrouvez un compagnon, parmi tous les autres."}
              </p>
            </div>
            <span className="heading-emblem">
              <Icon name="leaf" size={32} />
            </span>
          </div>
          <section
            className="collection-toolbar"
            aria-label="Affichage de la collection"
          >
            <div className="segmented">
              <button
                className={view === "boxes" ? "active" : ""}
                aria-pressed={view === "boxes"}
                onClick={() => switchView("boxes")}
              >
                <Icon name="box" size={17} /> Par boîte
              </button>
              <button
                className={view === "all" ? "active" : ""}
                aria-pressed={view === "all"}
                onClick={() => switchView("all")}
              >
                <Icon name="grid" size={17} /> Tout voir
              </button>
            </div>
            <span className="small muted">
              {pokemon.length} Pokémon · {boxCount}{" "}
              {boxCount > 1 ? "boîtes" : "boîte"}
            </span>
          </section>
          {view === "boxes" ? (
            <section className="box-panel" aria-label={`Boîte ${box + 1}`}>
              <div className="box-header">
                <div className="box-title">
                  <span className="box-icon">
                    <Icon name="box" />
                  </span>
                  <div>
                    <h2>Boîte {String(box + 1).padStart(2, "0")}</h2>
                    <span>{boxPokemon.length} / 30 emplacements</span>
                  </div>
                </div>
                <div className="box-controls">
                  <button
                    className="icon-button"
                    disabled={box === 0}
                    aria-label="Boîte précédente"
                    onClick={() => setBox((b) => b - 1)}
                  >
                    <Icon name="chevron-left" />
                  </button>
                  <select
                    aria-label="Choisir une boîte"
                    value={box}
                    onChange={(e) => setBox(Number(e.target.value))}
                  >
                    {Array.from({ length: boxCount }, (_, i) => (
                      <option value={i} key={i}>
                        Boîte {String(i + 1).padStart(2, "0")}
                      </option>
                    ))}
                  </select>
                  <button
                    className="icon-button"
                    disabled={box === boxCount - 1}
                    aria-label="Boîte suivante"
                    onClick={() => setBox((b) => b + 1)}
                  >
                    <Icon name="chevron-right" />
                  </button>
                </div>
              </div>
              <div className="box-grid">
                {Array.from({ length: 30 }, (_, slot) => {
                  const p = positions.get(box * 30 + slot);
                  return p ? (
                    <PokemonCard
                      key={p.id}
                      pokemon={p}
                      selected={selected === p.id}
                      onSelect={(button) => {
                        selectedButton.current = button;
                        setSelected(p.id);
                      }}
                    />
                  ) : (
                    <div
                      className="empty-slot"
                      key={`empty-${slot}`}
                      aria-label={`Emplacement ${slot + 1} vide`}
                    >
                      <span className="slot-number">
                        {String(slot + 1).padStart(2, "0")}
                      </span>
                      <Ball />
                    </div>
                  );
                })}
              </div>
              <div className="box-footer">
                <span>
                  <span className="status-dot" />{" "}
                  {boxPokemon.length
                    ? "Sélectionnez un Pokémon pour découvrir sa fiche."
                    : "Cette boîte attend ses premiers compagnons."}
                </span>
                <span>
                  {String(box + 1).padStart(2, "0")} /{" "}
                  {String(boxCount).padStart(2, "0")}
                </span>
              </div>
            </section>
          ) : (
            <section className="all-panel" aria-label="Tous les Pokémon">
              <div className="filters">
                <label className="search-field">
                  <Icon name="search" size={19} />
                  <input
                    value={filters.query}
                    onChange={(e) => changeFilter("query", e.target.value)}
                    placeholder="Nom, n° Pokédex, jeu d’origine…"
                    aria-label="Rechercher un Pokémon"
                  />
                  {filters.query && (
                    <button
                      className="icon-button"
                      aria-label="Effacer la recherche"
                      onClick={() => changeFilter("query", "")}
                    >
                      <Icon name="close" size={16} />
                    </button>
                  )}
                </label>
                <div className="filter-row">
                  <select
                    aria-label="Filtrer par type"
                    value={filters.type}
                    onChange={(e) => changeFilter("type", e.target.value)}
                  >
                    <option value="">Tous les types</option>
                    {TYPE_NAMES.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                  <select
                    aria-label="Filtrer par format PK"
                    value={filters.generation}
                    onChange={(e) => changeFilter("generation", e.target.value)}
                  >
                    <option value="">Tous les formats</option>
                    {[3, 4, 5, 6, 7, 8, 9].map((g) => (
                      <option key={g} value={g}>
                        PK{g}
                      </option>
                    ))}
                  </select>
                  <button
                    className={`filter-chip ${filters.shiny ? "active" : ""}`}
                    aria-pressed={filters.shiny}
                    onClick={() => changeFilter("shiny", !filters.shiny)}
                  >
                    <Icon name="sparkles" size={16} /> Chromatiques
                  </button>
                  <select
                    className="sort-select"
                    aria-label="Trier les Pokémon"
                    value={filters.sort}
                    onChange={(e) => changeFilter("sort", e.target.value)}
                  >
                    <option value="position">Ordre des boîtes</option>
                    <option value="dex">N° Pokédex</option>
                    <option value="name">Nom : A → Z</option>
                    <option value="level">Niveau décroissant</option>
                  </select>
                </div>
              </div>
              <div className="results-heading" aria-live="polite">
                <span>
                  {filtered.length}{" "}
                  {filtered.length === 1 ? "Pokémon trouvé" : "Pokémon trouvés"}
                </span>
                {(filters.query ||
                  filters.type ||
                  filters.shiny ||
                  filters.generation) && (
                  <button
                    className="text-button"
                    onClick={() => {
                      setFilters(DEFAULT_FILTERS);
                      setPage(0);
                    }}
                  >
                    Réinitialiser les filtres
                  </button>
                )}
              </div>
              {filtered.length ? (
                <div className="collection-grid">
                  {filtered
                    .slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
                    .map((p) => (
                      <PokemonCard
                        key={p.id}
                        pokemon={p}
                        selected={selected === p.id}
                        onSelect={(button) => {
                          selectedButton.current = button;
                          setSelected(p.id);
                        }}
                        showBox
                      />
                    ))}
                </div>
              ) : (
                <div className="empty-results">
                  <Icon name={pokemon.length ? "search" : "box"} size={40} />
                  <h2>
                    {pokemon.length
                      ? "Aucun compagnon trouvé."
                      : "Une nouvelle collection commence ici."}
                  </h2>
                  <p>
                    {pokemon.length
                      ? "Essayez un autre nom ou ajustez vos filtres."
                      : "Les Pokémon présents dans votre base apparaîtront ici."}
                  </p>
                </div>
              )}
              {filtered.length > PAGE_SIZE && (
                <div className="pagination">
                  <button
                    className="button"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Précédent
                  </button>
                  <span>
                    Page {page + 1} / {Math.ceil(filtered.length / PAGE_SIZE)}
                  </span>
                  <button
                    className="button"
                    disabled={(page + 1) * PAGE_SIZE >= filtered.length}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Suivant
                  </button>
                </div>
              )}
            </section>
          )}
          <div className="workspace-note">
            <Icon name="leaf" size={15} />
            <span>Un petit chez-soi pour de grandes aventures.</span>
            <span>BRING BACK HOME</span>
          </div>
        </div>
      </main>
      {current && (
        <PokemonDetails
          key={current.id}
          pokemon={current}
          onClose={closeDetails}
        />
      )}
      {showProfile && (
        <Profile trainer={trainer} onClose={() => setShowProfile(false)} />
      )}
    </div>
  );
}
function Brand() {
  return (
    <div className="brand">
      <span className="brand-icon">
        <Icon name="box" size={23} />
      </span>
      <span>
        bring back
        <strong>
          HOME<span className="brand-dot">.</span>
        </strong>
      </span>
    </div>
  );
}
function PokemonCard({
  pokemon: p,
  selected,
  onSelect,
  showBox = false,
}: {
  pokemon: Pokemon;
  selected: boolean;
  onSelect: (button: HTMLButtonElement) => void;
  showBox?: boolean;
}) {
  return (
    <button
      className={`pokemon-card ${selected ? "selected" : ""}`}
      aria-pressed={selected}
      aria-label={`${p.name}, niveau ${p.level}${p.is_shiny ? ", chromatique" : ""}, boîte ${Math.floor(p.position / 30) + 1}, emplacement ${(p.position % 30) + 1}`}
      onClick={(e) => onSelect(e.currentTarget)}
    >
      <span className="slot-number">
        {showBox
          ? `N° ${String(p.species_id).padStart(4, "0")}`
          : String((p.position % 30) + 1).padStart(2, "0")}
      </span>
      {!!p.is_shiny && (
        <span className="card-shiny">
          <Icon name="sparkles" size={13} />
        </span>
      )}
      <PokemonArt pokemon={p} />
      <strong>{p.name}</strong>
      <span className="card-meta">
        {showBox
          ? `Boîte ${String(Math.floor(p.position / 30) + 1).padStart(2, "0")} · `
          : ""}
        Niv. {p.level}
      </span>
      {selected && (
        <span className="selection-indicator">
          <Icon name="check" size={11} />
        </span>
      )}
    </button>
  );
}
function Onboarding({
  onCreated,
  createProfile,
}: {
  onCreated: (trainer: Trainer) => void;
  createProfile: typeof createTrainer;
}) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      onCreated(await createProfile(name));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <main className="welcome-screen">
      <div className="welcome-card">
        <Brand />
        <div className="welcome-symbol">
          <Ball />
          <Icon name="sparkles" size={30} />
        </div>
        <span className="eyebrow">UN NOUVEAU DÉPART</span>
        <h1>
          Ils ont trouvé
          <br />
          leur maison.
        </h1>
        <p>
          Et vous, comment vous appelez-vous ?<br />
          Créez votre profil pour retrouver vos compagnons.
        </p>
        <form onSubmit={submit}>
          <label htmlFor="trainer-name">Votre nom de dresseur</label>
          <input
            id="trainer-name"
            autoFocus
            autoComplete="nickname"
            placeholder="Ex. Sacha"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            aria-describedby="name-help"
            disabled={saving}
          />
          <div className="input-help" id="name-help">
            <span>1 à 12 caractères</span>
            <span>{Array.from(name.trim()).length} / 12</span>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button
            className="button primary"
            disabled={
              saving || !name.trim() || Array.from(name.trim()).length > 12
            }
          >
            {saving ? "Création de votre profil…" : "Entrer à la maison"}
            <Icon name="arrow" size={19} />
          </button>
        </form>
        <div className="welcome-footnote">
          <Icon name="user" size={16} />
          <span>
            Vos identifiants de dresseur sont générés une seule fois et
            conservés avec votre profil local.
          </span>
        </div>
      </div>
      <span className="welcome-caption">
        VOS COMPAGNONS. VOTRE COLLECTION. VOTRE MAISON.
      </span>
    </main>
  );
}
function Profile({
  trainer,
  onClose,
}: {
  trainer: Trainer;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="profile-dialog"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="detail-top">
        <span className="eyebrow">CARTE DE DRESSEUR</span>
        <button
          className="icon-button"
          aria-label="Fermer le profil"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <span className="avatar profile-avatar">
        {Array.from(trainer.name)[0]}
      </span>
      <h2>{trainer.name}</h2>
      <div className="trainer-identifiers">
        <div>
          <span>TID</span>
          <strong>{trainerId(trainer.tid)}</strong>
        </div>
        <div>
          <span>SID</span>
          <strong>{trainerId(trainer.sid)}</strong>
        </div>
      </div>
      <p className="muted small">
        Votre identité locale, conservée pour les futurs échanges.
      </p>
    </dialog>
  );
}
export default App;
