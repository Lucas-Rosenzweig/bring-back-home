# Fixture FRLG synthétique

`synthetic-trade-v1.jsonl` est produit exclusivement par
`SyntheticFrlgHostTransport` avec des adresses, identifiants, noms et Pokémon
fabriqués pour les tests. Il couvre un échange follower complet, la sauvegarde
et la sortie. Il ne provient pas d'une capture Switch et ne doit jamais être
remplacé directement par une capture live.

Le test d'intégration régénère la trace sous horloge Trio déterministe, exige
une égalité octet pour octet avec cette fixture, puis rejoue le même chemin de
client.
