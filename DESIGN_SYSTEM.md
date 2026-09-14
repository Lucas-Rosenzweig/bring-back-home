# Bring Back Home · Design system

Interface desktop française, inspirée des codes de Pokémon HOME : menthe,
dégradés végétaux, panneaux clairs, silhouettes de Poké Ball et espaces réguliers.
Les éléments visuels sont construits en CSS et SVG. La référence Game UI Database
fournie n’était pas accessible pendant l’implémentation.

## Fondations

Les variables de `src/App.css` sont la source des styles partagés.

| Token | Usage |
| --- | --- |
| `--color-ink` | Texte principal, vert profond |
| `--color-muted` | Texte secondaire |
| `--color-primary` / `--color-primary-dark` | Actions et sélection |
| `--color-surface` / `--color-canvas` | Panneaux et fond |
| `--color-border` | Séparation douce |
| `--gradient-home` | En-têtes des boîtes et avatar |
| `--gradient-primary` | Action principale et marque |
| `--radius-sm`, `--radius-md`, `--radius-lg` | Rayons 8, 14, 22 px |
| `--space-*` | Échelle 4, 8, 12, 16, 24, 32 px |
| `--shadow-panel` | Relief discret des panneaux |

Police système : Avenir Next, Avenir, Segoe UI, sans-serif. Aucun téléchargement
nécessaire pour les polices. Titres compacts, labels espacés, chiffres lisibles.
Fenêtre initiale : 1440 × 960 ; minimum : 1100 × 760. À faible hauteur,
le contenu reste accessible par défilement. Pas de version mobile.

## Classes et composants

- `.button`, `.button.primary`, `.icon-button`, `.text-button` : actions,
  états désactivés et focus visible.
- `.segmented`, `.nav-item` : modes d’affichage et navigation.
- `.box-panel`, `.box-header`, `.box-grid`, `.empty-slot` : une boîte, 6 × 5 cases.
- `.pokemon-card`, `.selected` : consultation, survol et sélection explicite.
- `.filters`, `.search-field`, `.filter-chip` : recherche et filtres combinables.
- `.detail-panel`, `.detail-tabs`, `.info-list`, `.stat-table`, `.move` : fiche latérale.
- `.type-badge`, `.type-*` : types nommés et couleurs sémantiques.
- `.welcome-*`, `.profile-dialog`, `.avatar` : premier lancement et profil.
- `.eyebrow`, `.small`, `.muted` : hiérarchie typographique.
- `Icon`, `Ball`, `PokemonArt`, `TypeBadge` : primitives React réutilisables.

Les cartes sont des boutons accessibles au clavier. La fiche reçoit le focus
à l’ouverture, Échap la ferme et rend le focus à la carte si elle est encore
présente. Les onglets répondent aux flèches gauche/droite. Le profil utilise un
`dialog` natif. Les animations respectent `prefers-reduced-motion`.

## Données et états

Un emplacement vide n’est pas interactif. Une collection vide, une recherche
sans résultat, le chargement et une erreur de connexion ont chacun un état
explicite. Les données individuelles absentes restent « Non renseigné » / « — ».
Le type par défaut vient du référentiel local ; une forme alternative sans types
explicites n’hérite pas d’un type potentiellement erroné.

Les sprites / illustrations sont embarqués dans `public/assets/pokemon`.
`PokemonArt` charge d’abord l’image locale. En cas d’erreur seulement, il tente
la même image sur PokeAPI/sprites ; un deuxième échec affiche une Poké Ball.
Changer de Pokémon, de taille ou de variante chromatique réinitialise ce parcours.
Les formes non résolues utilisent directement la Poké Ball afin de ne pas montrer
une illustration incorrecte. Les fichiers des formes alternatives sont déjà inclus
pour leur futur raccordement au décodeur.

## Vérification visuelle en développement

Avec Vite lancé, `/tests/preview.html` fournit 65 Pokémon fictifs, trois boîtes
et des métadonnées pour vérifier les composants. `?empty` montre une collection
vide ; `?onboarding` montre la création du profil. Ce banc d’essai ne lit ni
n’écrit SQLite et n’est pas inclus dans le build de production.
