# Bring Back Home

Banque Pokémon locale pour desktop, construite avec Tauri 2, React et SQLite.

```sh
npm install
npm run tauri dev
```

Le navigateur seul ne dispose pas du pont SQLite Tauri : l’application y affiche
un message explicite. Pour inspecter les styles avec des données fictives, ouvrir
`http://localhost:1420/tests/preview.html` après `npm run dev`.

## Fonctionnalités

- Un profil local : nom (1–12 caractères Unicode), TID et SID.
- Une boîte à la fois, 30 emplacements, navigation et sélection directe de boîte.
- Toute la collection : recherche sans accents par nom, espèce, numéro ou jeu ;
  filtres par type, chromatique et format PK ; tri ; pages de 60 Pokémon.
- Fiche latérale avec résumé, dresseur d’origine, IV/EV et capacités.
- Consultation uniquement : aucune modification, importation ou exportation de PK*.

Le design system et les classes sont décrits dans [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## SQLite et métadonnées

La base `sqlite:bring-back-home.db` réside dans le répertoire applicatif Tauri.
Les migrations existantes sont conservées. La migration 3 ajoute :

- `storage_position` : entier unique, base zéro ; boîte = position / 30,
  emplacement = position modulo 30. Les données déjà présentes sont placées dans
  un ordre stable (`created_at`, `id`). Des positions absentes sont présentées
  dans les premiers emplacements libres, sans écriture par le front.
- `details_json` : projection facultative pour les informations détaillées.
- Un trigger empêchant la création d’un deuxième profil.

Les fichiers bruts `raw_data` restent inchangés et ne transitent pas par le front.
Le décodage des fichiers PK3–PK9 n’est pas implémenté : le futur décodeur devra
renseigner `details_json` et les positions lors de l’import. Exemple de contrat :

```json
{
  "form": "Alola",
  "types": ["Glace"],
  "nature": "Timide",
  "ability": "Rideau Neige",
  "heldItem": "Aucun",
  "ivs": {"hp":31,"attack":0,"defense":31,"specialAttack":31,"specialDefense":31,"speed":31},
  "evs": {"hp":4,"attack":0,"defense":0,"specialAttack":252,"specialDefense":0,"speed":252},
  "stats": {"hp":145,"attack":64,"defense":95,"specialAttack":133,"specialDefense":120,"speed":177},
  "moves": [{"name":"Laser Glace","type":"Glace","pp":10,"maxPp":10}],
  "originalTrainer": {"name":"Sacha","tid":12345,"sid":54321},
  "metLocation": "Route 1",
  "metDate": "2026-09-14",
  "ball": "Poké Ball"
}
```

Tous les champs sont facultatifs. Aucune statistique n’est fabriquée quand elle
manque. Le dresseur d’origine du Pokémon n’est jamais remplacé par le profil local.

Le TID et le SID sont deux entiers 16 bits uniformes générés par
`crypto.getRandomValues`, sans dérivation du nom. Le format est celui des
identifiants internes classiques ; le générateur pseudo-aléatoire d’une console
particulière n’est pas émulé. Ils sont sauvegardés une seule fois dans SQLite.
Cela prépare l’identité ; les échanges et la compatibilité par jeu restent à implémenter.

## Référentiel et illustrations

Les 1 025 noms français et types par défaut sont embarqués dans
`src/data/species.json`, extraits le 14 septembre 2026 des CSV du projet
[PokeAPI](https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv).
Les illustrations proviennent de [PokeAPI/sprites](https://github.com/PokeAPI/sprites)
et nécessitent le réseau ; une silhouette de Poké Ball sert de repli hors ligne.
Les illustrations des formes alternatives restent à raccorder au décodeur.
Pokémon et ses illustrations appartiennent à leurs ayants droit respectifs.

## Vérifications

```sh
npm run test
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

Les tests utilisent Node/tsx et Python 3 (sqlite3 standard). Ils vérifient les
filtres, positions, projections invalides, données absentes, identifiants et
migrations sur une base isolée. Le banc d’essai visuel est dans `tests/preview.*`.
