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
Les illustrations proviennent de [PokeAPI/sprites](https://github.com/PokeAPI/sprites).
Les PNG sont embarqués dans `public/assets/pokemon` puis copiés dans le build Vite
et le bundle Tauri : aucun réseau n’est utilisé quand l’image locale est présente.
Le chargement suit cet ordre : **local → même image en ligne → Poké Ball**.
La tentative en ligne ne démarre qu’après une erreur de chargement locale ; une
erreur en ligne affiche le placeholder sans boucle de tentatives.

Le bundle comprend les sprites et illustrations officielles, normaux et
chromatiques, ainsi que les variantes femelles et formes alternatives disponibles.
Il exclut les doublons par version historique du jeu et les animations non utilisées.
`manifest.json` enregistre la révision source, la taille et le SHA Git de chaque PNG.

```sh
npm run assets:download  # Reprendre le téléchargement de la révision enregistrée
npm run assets:verify    # Vérifier toutes les images hors ligne
npm run assets:download -- --update  # Actualiser depuis la source
```

Le téléchargement vérifie l’intégrité des fichiers et reprend les fichiers manquants
ou corrompus. Les ressources sont versionnées avec le projet.
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

## Activer les fixtures dans la vraie base locale

Fermez la fenêtre Tauri avant chaque bascule et attendez la fin de la commande
avant de la relancer. Le serveur Vite peut rester lancé.

```sh
npm test enable   # Sauvegarder la base puis charger les fixtures
npm test status   # Afficher la base et la présence d'une sauvegarde
npm test disable  # Restaurer la base complète d'origine
npm test          # Lancer les tests automatisés, sans basculer la base locale
```

Par défaut, l’activation crée **960 Pokémon dans 32 boîtes** et le dresseur
**Test HOME** (TID `12345`, SID `54321`). Les fixtures couvrent PK3–PK9,
plusieurs types, niveaux, genres, chromatiques, surnoms, IV/EV et capacités.
Certaines fiches sont volontairement incomplètes pour vérifier les états absents.
Les statistiques sont synthétiques et ne simulent pas les calculs des jeux.
Les BLOB `raw_data` portent le marqueur `BBH_FIXTURE_NOT_A_VALID_PK_FILE` :
ce ne sont **pas des fichiers PK* valides**, ni des Pokémon à exporter/échanger.

```sh
npm test enable -- --count 1800
# Base alternative (utiliser le même --db pour enable, status et disable) :
npm test enable -- --db /chemin/collection.db --count 90
npm test disable -- --db /chemin/collection.db
```

La base doit déjà être initialisée par Tauri. Son emplacement est résolu depuis
`tauri.conf.json` et le répertoire de configuration Tauri de l’OS. Python 3 est
nécessaire ; macOS/Linux utilisent aussi `lsof` pour détecter une base ouverte.
Sous Windows, un contrôle de partage exclusif du fichier remplit ce rôle.

La sauvegarde complète est placée **à côté de la base**, avec le suffixe
`.fixtures-original.sqlite3`. L’API de sauvegarde SQLite inclut les écritures
validées dans le WAL ; une simple copie du fichier `.db` n’est pas utilisée.
Le remplissage s’effectue dans une transaction après sauvegarde vérifiée.
Les autres tables et l’historique de migration restent en place pendant les tests.

Une seconde activation est refusée tant que la sauvegarde existe. `disable`
restaure toutes les tables et le schéma d’origine, puis supprime la sauvegarde
seulement après réussite. Toutes les modifications faites pendant la session
fixtures sont donc abandonnées. Sans sauvegarde, `disable` ne modifie rien.

En cas d’erreur de remplissage ou de restauration, conservez la sauvegarde et
relancez `disable` après avoir fermé Tauri. Si le processus a été interrompu
brutalement, un dossier `.fixtures-lock` ou un fichier `.pending` peut rester :
ne retirez le verrou qu’après avoir vérifié qu’aucune commande fixtures ne tourne ;
conservez et vérifiez les sauvegardes avant toute reprise. `status` indique la
présence d’une sauvegarde récupérable, y compris après une activation interrompue.
