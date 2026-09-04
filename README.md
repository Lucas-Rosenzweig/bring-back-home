# Bring Back Home

Bring Back Home est un client Linux expérimental capable de rejoindre une
session Nintendo Switch LDN comme station et d’effectuer un échange local avec
Pokémon Rouge Feu ou Vert Feuille. Un mode replay déterministe permet aussi de
développer sans console.

Le chemin FRLG a été validé sur une carte Intel AX200, mais reste expérimental :
conservez toujours une copie de vos sauvegardes et de vos Pokémon avant un test
matériel.

## Fonctionnalités

- découverte, authentification et adressage Nintendo LDN sans bibliothèque LDN
  externe ;
- follower PIA/Reliable/RFU compatible avec un salon créé par la Switch ;
- échange de un à six Pokémon Gen III à partir de fichiers `.pk3` ;
- export atomique du Pokémon reçu uniquement après confirmation de l’échange ;
- sortie FRLG progressive ou déconnexion immédiate après la sauvegarde ;
- captures JSONL privées et replays synthétiques sans privilèges ;
- API typée permettant d’ajouter d’autres jeux sans coupler leur protocole à
  FRLG.

## Prérequis

- Linux et Python 3.13 ;
- [`uv`](https://docs.astral.sh/uv/) ;
- une interface Wi-Fi compatible avec les modes station et monitor ;
- `pkexec` ou un moyen équivalent de donner au processus les privilèges réseau ;
- les `prod.keys` de votre propre console ;
- la passphrase LDN correspondant au jeu.

Le programme prend temporairement le contrôle du PHY Wi-Fi sélectionné. Une
connexion réseau utilisant ce même PHY sera donc interrompue pendant le test.

## Installation

```bash
git clone <URL_DU_DEPOT>
cd bring-back-home
uv sync
mkdir -p .switch output captures
chmod 700 .switch output captures
cp /chemin/vers/prod.keys .switch/prod.keys
chmod 600 .switch/prod.keys
```

Les clés, passphrases, captures, exports et fichiers `.pk3` sont ignorés par
Git. Ne les déplacez pas dans une fixture ou un autre répertoire versionné.

### Configurer la passphrase LDN

Le format recommandé est un catalogue TOML. Le client choisit la passphrase à
partir du communication ID observé :

```toml
[passphrases]
"0100000000000000" = "PASSPHRASE_ASCII_OU_128_CARACTERES_HEXADECIMAUX"
```

Enregistrez-le dans `.switch/ldn_passphrases.toml`, puis protégez-le :

```bash
chmod 600 .switch/ldn_passphrases.toml
```

Un fichier contenant uniquement la passphrase ou la variable d’environnement
`LDN_PASSPHRASE` sont aussi acceptés. Évitez la variable d’environnement sur
une machine multi-utilisateur.

## Préparer les Pokémon

Le client accepte de un à six fichiers `.pk3` Gen III. Une entrée peut faire
80 octets (format boîte) ou 100 octets (format équipe) ; elle est validée avant
que le client prenne le contrôle de la radio.

Les arguments positionnels forment l’équipe du client. `--trades` indique le
nombre d’échanges et `--slots` les emplacements proposés, indexés à partir de
zéro. Par exemple, `--trades 2 --slots 0,2` propose successivement le premier
et le troisième Pokémon de l’équipe.

## Effectuer un échange FRLG

1. Sur la Switch, créer un salon d’échange FRLG et le laisser en attente.
2. Vérifier qu’aucun autre `pokemon_trade_cli.py` ne tourne.
3. Lancer le client avec les chemins absolus recommandés ci-dessous.
4. Attendre `room_entered`, puis s’asseoir et accepter l’échange sur la Switch.
5. Ne pas interrompre le processus entre `committed` et `saving`.
6. Attendre `completed` et le retour de la radio avant de recréer un salon.

```bash
pkexec /usr/bin/env PYTHONDONTWRITEBYTECODE=1 \
  "$PWD/.venv/bin/python" "$PWD/pokemon_trade_cli.py" \
  --game firered \
  --trainer-id 1 --secret-id 2 --name EMU \
  --passphrase-file "$PWD/.switch/ldn_passphrases.toml" \
  --trades 1 --slots 0 \
  --output-dir "$PWD/output/frlg-run" \
  "$PWD/offered-1.pk3"
```

`--game` accepte `firered` ou `leafgreen`. Le nom contient de un à sept
caractères Gen III. Les IDs et le nom décrivent le joueur émulé ; ils ne sont
pas lus depuis le Pokémon offert.

Les jalons normaux sont :

```text
ldn_ready
peer_connected
room_entered
menu_ready
offered #1
committed #1
saving
leaving
completed
```

Le fichier reçu est exporté sous `trade-01.pk3` dans `--output-dir`. Comme le
processus live est lancé avec `pkexec`, le fichier peut appartenir à root. Pour
le rendre à l’utilisateur courant sans élargir ses permissions :

```bash
pkexec chown "$USER":"$(id -gn)" "$PWD/output/frlg-run/trade-01.pk3"
```

### Couper la session dès la fin de l’échange

Ajoutez `--disconnect-after-trade` pour couper la session immédiatement après
la confirmation de la sauvegarde finale :

```bash
pkexec /usr/bin/env PYTHONDONTWRITEBYTECODE=1 \
  "$PWD/.venv/bin/python" "$PWD/pokemon_trade_cli.py" \
  --disconnect-after-trade \
  --game firered --trainer-id 1 --secret-id 2 --name EMU \
  --passphrase-file "$PWD/.switch/ldn_passphrases.toml" \
  "$PWD/offered-1.pk3"
```

Cette option saute la négociation « Annuler » et les standbys de sortie, mais
ne coupe ni pendant l’animation ni pendant la sauvegarde. Sans l’option, le
client effectue la sortie progressive du salon.

### Capturer une session pour diagnostic

```bash
# Ajouter à la commande live :
--capture "$PWD/captures/frlg-run.jsonl" --verbose
```

Une capture contient des identifiants de session et des données Pokémon. Elle
doit rester locale, en mode `0600`, et ne doit jamais être publiée telle quelle.

## Replay sans matériel

Le replay exécute exactement la même machine d’état sur une capture synthétique
et ne demande aucun privilège :

```bash
.venv/bin/python pokemon_trade_cli.py \
  --replay tests/fixtures/frlg/synthetic-trade-v1.jsonl \
  --game firered --trainer-id 1 --secret-id 2 --name EMU \
  offered-1.pk3
```

Une capture live ne devient pas automatiquement une fixture : elle doit être
expurgée et réencodée avec une identité, un réseau et des Pokémon synthétiques.

## Nettoyage radio

Le programme crée temporairement `mon0` et `ldnclient`, les exclut de
NetworkManager puis les retire à la sortie. `Ctrl+C`, `SIGTERM` et `SIGHUP`
passent par le nettoyage normal. Après un `SIGKILL`, relancez l’outil : la
nouvelle lease radio reprend et nettoie les interfaces résiduelles.

## Dépannage

- **Aucun salon trouvé** : vérifier que la Switch attend dans un salon, que le
  catalogue contient le bon communication ID et que les canaux autorisés
  incluent celui du salon.
- **Erreur avant `peer_connected`** : vérifier la passphrase, `prod.keys`, le
  PHY choisi et l’absence d’un autre client radio.
- **Blocage avant `menu_ready`** : garder la Switch dans la salle et augmenter
  temporairement `--phase-timeout`; l’entrée observée sur AX200 peut dépasser
  50 secondes.
- **Erreur après `committed`** : conserver la capture privée et le fichier
  exporté. Ne pas relancer immédiatement tant que `mon0` ou `ldnclient` existe.
- **Fichier exporté illisible par l’utilisateur** : utiliser la commande
  `chown` ciblée indiquée plus haut, sans modifier le mode `0600`.

Toutes les options sont disponibles avec :

```bash
.venv/bin/python pokemon_trade_cli.py --help
```

## Développement

```bash
uv sync
.venv/bin/python -m unittest discover -s tests
.venv/bin/pyright pokemon_trade pokemon_trade_cli.py
```

Architecture, protocole et extension :

- [architecture du client](docs/architecture/pokemon-trade-client.md) ;
- [guide FRLG détaillé](docs/guides/frlg-trade.md) ;
- [machine d’état FRLG](docs/protocols/frlg/state-machine.md) ;
- [pile filaire FRLG](docs/protocols/frlg/wire-stack.md) ;
- [ajouter un jeu](docs/guides/adding-a-game.md) ;
- [validation matérielle AX200](docs/testing/frlg-live.md).
