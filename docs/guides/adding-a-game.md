# Ajouter un jeu

1. Relever et vérifier localement les signatures LDN du jeu (communication ID,
   scène, version et application data); ne pas activer l’auto-détection avec
   une valeur simplement observée dans un autre dépôt.
2. Créer le plugin sous `pokemon_trade/games/<jeu>/` et ne dépendre du noyau que
   via `TradeRequest`, `TradeResult`, événements et `DatagramTransport`.
3. Identifier le protocole réellement présent au-dessus d’UDP. Réévaluer PIA,
   Reliable, GBA/RFU et la machine métier; aucune de ces couches ne doit être
   promue dans le noyau commun à partir d’un seul jeu.
4. Produire des vecteurs et replays synthétiques. Une capture live contient des
   identifiants et potentiellement des données Pokémon : elle reste locale,
   ignorée par Git, et doit être expurgée puis re-encodée avant de devenir une
   fixture.
5. Définir explicitement les conditions de commit et d’annulation. Les artefacts
   reçus ne peuvent être exposés qu’après une preuve protocolaire de commit.

Une proposition d’extraction commune doit inclure des vecteurs indépendants
provenant d’au moins deux jeux et démontrer que les versions, tailles et états
ont les mêmes garanties.
