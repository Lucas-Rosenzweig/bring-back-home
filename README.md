# Bring Back Home — LDN radio lab

Ce laboratoire découvre une advertisement Nintendo LDN, la déchiffre avec les
clés de la console, rejoint la session comme station puis affiche les
datagrammes PIA reçus sur UDP/12345. Il n'envoie aucun message PIA applicatif.
La pile LDN utilisée ici est implémentée dans le projet : aucune bibliothèque
`ldn` externe n'est utilisée.

Le découpage volontairement minimal est le suivant :

- `ldn_protocol.py` : structures binaires, dérivation des clés, AES-CTR/GCM,
  challenge HMAC et authentification ;
- `Wifi/LdnStation.py` : création de la station, association et control port
  directement via nl80211 ;
- `ldn_client.py` : orchestration de la connexion et observation UDP/PIA.

## Préparation

```bash
uv sync
mkdir -p .switch
cp /chemin/vers/prod.keys .switch/prod.keys
```

La passphrase LDN du jeu doit rester hors du dépôt. Elle peut être fournie par
un fichier brut ignoré par Git :

```bash
printf '%s' 'PASSPHRASE_DU_JEU' > .switch/ldn.passphrase
chmod 600 .switch/ldn.passphrase
```

Un catalogue TOML est également accepté. Le programme sélectionne alors la
passphrase d'après le communication ID de chaque advertisement :

```toml
[passphrases]
"0100000000000000" = "PASSphrase_ASCII_ou_128_caracteres_hexadecimaux"
```

## Découverte et déchiffrement uniquement

```bash
sudo env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python radio_lab.py --discovery-only
```

## Association LDN et observation PIA

```bash
sudo env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python radio_lab.py \
  --passphrase-file .switch/ldn_passphrases.toml
```

Sans `--communication-id` ni `--scene-id`, la première session joignable ayant
une entrée dans le catalogue est utilisée. La version applicative annoncée par
l'hôte est reprise automatiquement.

Le programme exclut temporairement `mon0` et `ldnclient` de NetworkManager,
libère le PHY, puis restaure les interfaces à la sortie. `Ctrl+C`, `SIGTERM` et
`SIGHUP` passent par ce nettoyage. Un `SIGKILL` ne peut pas être nettoyé par un
programme ; dans ce cas, une relance reprend et supprime les interfaces LDN
résiduelles.

Certains pilotes Intel filtrent les advertisements LDN broadcast une fois la
station associée. Après un `AUTH_SUCCESS`, si aucune action frame de l'hôte
n'est reçue, le client applique le mécanisme d'allocation LDN : premier slot
libre et adresse `169.254.<réseau>.<slot + 1>`. Le fallback est refusé si des
advertisements arrivent mais sont invalides ou si la table connue est pleine.
