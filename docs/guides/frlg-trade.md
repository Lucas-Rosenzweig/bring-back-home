# Échange FRLG en follower

Le client rejoint un salon FRLG créé par une Switch Leader. Il n’est jamais
hôte, ne joue aucun combat et n’envoie aucune commande réservée au Leader.

## Préparation

1. Créer un salon d’échange local sur la Switch et le laisser en attente.
2. Préparer une équipe de un à six `.pk3` Gen III (80 ou 100 octets ; le
   client normalise les entrées boîte à 100 octets).
3. Fournir une identité locale synthétique cohérente : nom Gen III de 1 à 7
   caractères, trainer ID et secret ID. Ces valeurs servent aux blocs
   LinkPlayer, TrainerCard et NI mais ne sont pas affichées dans les logs.
4. Lancer un seul client privilégié. Une exécution interrompue doit être
   contrôlée avant de recréer le salon ; ne jamais lancer deux joiners dans le
   même salon.

```bash
pkexec /usr/bin/env PYTHONDONTWRITEBYTECODE=1 \
  "$PWD/.venv/bin/python" "$PWD/pokemon_trade_cli.py" \
  --game firered --trainer-id 1 --secret-id 2 --name EMU \
  --passphrase-file "$PWD/.switch/ldn_passphrases.toml" \
  --trades 1 --slots 0 offered-1.pk3 offered-2.pk3
```

Le choix `--game firered|leafgreen` configure la variante Gen III et limite la
découverte aux signatures LDN connues pour FRLG. Il ne transforme pas la
session d’un autre jeu en session FRLG.

## Déroulement et export

Les étapes visibles sont `ldn_ready`, `peer_connected`, `room_entered`,
`menu_ready`, `offered`, `committed`, `saving`, `leaving` et `completed`. Les
fichiers `trade-01.pk3`, etc., sont écrits atomiquement dans `--output-dir`
uniquement après `committed`; une annulation antérieure ne crée aucun fichier.
Le délai de phase vaut 90 secondes par défaut : l’entrée AX200 observée peut
prendre plus de 50 secondes entre l’échange LinkPlayer et l’ouverture du menu.
`--phase-timeout` permet de l’ajuster pour un diagnostic sans modifier le
protocole.

Après la dernière ronde, le follower demande l’annulation de la salle. Attendre
la fermeture RFU et le retour à l’interface radio normale avant de relancer un
test. Ne conserver ni captures brutes, ni SSID, ni MAC, ni `.pk3` personnels
dans Git.

Pour couper la session dès que la sauvegarde finale est confirmée, ajouter
`--disconnect-after-trade`. Cette option saute la négociation d’annulation et
les standbys de sortie de salle, envoie directement la déconnexion RFU puis
rend la main au nettoyage LDN. Elle ne coupe jamais pendant l’animation ou la
sauvegarde ; sans cette option, la sortie progressive reste le comportement
par défaut.

## Replay

Une capture JSONL synthétique utilise le même client FRLG sans privilège :

```bash
.venv/bin/python pokemon_trade_cli.py \
  --replay tests/fixtures/frlg/synthetic-trade-v1.jsonl --game firered \
  --trainer-id 1 --secret-id 2 --name EMU offered-1.pk3 offered-2.pk3
```

Les captures réelles sont sensibles : les expurger et les réencoder dans un
contexte synthétique avant toute fixture. La validation matérielle finale reste
trois échanges AX200 consécutifs suivant `docs/testing/frlg-live.md`.

## État de validation

Le chemin live compose déjà LDN, PIA, Reliable, RFU, blocs de partie et les
LINKCMD follower dans cette bibliothèque. Il reste expérimental tant que la
matrice AX200 n’a pas produit trois échanges réels successifs ; ne pas traiter
un run isolé comme une sauvegarde fiable et conserver les Pokémon originaux.
