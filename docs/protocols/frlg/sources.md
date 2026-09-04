# Sources et provenance — FRLG

Le client FRLG sera une réimplémentation indépendante. Le dépôt local de
référence est une source comportementale et documentaire uniquement : il ne
doit jamais être importé ni copié dans ce projet.

| Énoncé | Provenance | Statut |
| --- | --- | --- |
| LDN : discovery, association, authentification et IPv4 | code existant de ce dépôt et [LDN Protocol](https://github.com/kinnay/NintendoClients/wiki/LDN-Protocol) | implémenté / testé |
| Datagrammes PIA sur UDP/12345 après LDN | captures locales du client live | observé |
| PIA et Reliable | [PIA Overview](https://github.com/kinnay/NintendoClients/wiki/PIA-Overview) et [PIA Protocol](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol) | implémenté, testé par vecteurs et replay |
| Jeu, RFU et formats Gen 3 | [pret/pokefirered](https://github.com/pret/pokefirered) | implémenté, testé synthétiquement et sur matériel |

La seule signature actuellement autorisée en auto-détection est
`0x01006FA0233F8000`. Toute autre valeur, notamment celle signalée par un
outil de référence, nécessite une capture locale expurgée et une validation
avant d’être ajoutée.
