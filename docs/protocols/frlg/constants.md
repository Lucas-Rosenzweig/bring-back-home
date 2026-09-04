# Constantes et structures FRLG

## `.pk3` Gen III

| Offset | Taille | Valeur |
| --- | ---: | --- |
| `0x00` | 4 | personnalité (`u32le`) |
| `0x04` | 4 | identifiant dresseur combiné (`u32le`) |
| `0x08` | 20 | surnom, langue, OT et marquages |
| `0x1C` | 2 | checksum des 48 octets déchiffrés (`u16le`) |
| `0x20` | 48 | quatre sous-structures chiffrées par XOR avec `PID ^ OTID` |
| `0x50` | 20 | état runtime du parti ; nul lors de la normalisation d’une entrée boîte |

Une entrée boîte mesure 80 octets. Une entrée de parti, qui est le format
public du client FRLG, mesure 100 octets. L’ordre physique des sous-structures
de 12 octets est choisi par `PID % 24`; le module `pokemon.py` conserve les
octets reçus sans utiliser de nom ou données de dresseur dans les logs.

## PIA / RFU

La clé de titre PIA FRLG est `83CA7FAB734C34633B10183526C1E85B`. Ce n’est pas
une clé de console : les `prod.keys`, passphrases LDN, SSID et identifiants de
session restent secrets et ne sont jamais versionnés. Le connect ID RFU et le
nonce PIA sont générés pour chaque exécution.

Le canal Reliable live utilise une fenêtre partagée de six trames, dont au
plus trois ACK émulateur `K`. Un datagramme PIA regroupe jusqu’à neuf messages
Reliable. Le RTO est calculé sur les sept derniers aller-retours propres :
`33 ms + 1,4 × médiane + 4 × écart absolu moyen`, plafonné à `670 ms`; avant
le premier échantillon, le bootstrap vaut `200 ms`. Une échéance ne réémet que
les deux plus anciens trous afin de ne pas transformer la récupération en
rafale sur la liaison AX200 demi-duplex.
