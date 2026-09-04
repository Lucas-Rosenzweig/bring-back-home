# Client abstrait d’échange Pokémon

Créer au-dessus du cœur LDN existant et inchangé un client d’échange Pokémon extensible par jeu, exposé comme bibliothèque Python typée et CLI fine. La première implémentation réimplémente indépendamment le protocole Pokémon Rouge Feu / Vert Feuille afin d’effectuer de un à six échanges locaux LDN comme follower face à une Switch leader et de restituer les Pokémon reçus en `.pk3`.

La compréhension partagée et les critères vérifiables se trouvent dans [facts.md](facts.md). Le chemin d’implémentation ordonné, les fichiers ciblés, les vérifications et les risques se trouvent dans [plan.md](plan.md).

## Condition de fin

Le goal est terminé lorsque la bibliothèque et la CLI exécutent le même chemin FRLG sur transport live et replay, que les résultats `.pk3` ne sont exposés qu’après commit, que les erreurs et annulations restaurent correctement la radio, que les tests automatisés acceptés passent et que trois échanges AX200 consécutifs satisfont la procédure matérielle documentée. La surface utilisateur expose une seule CLI avec un choix explicite du jeu Pokémon, et le guide d’extension doit empêcher de promouvoir PIA/RFU dans le noyau commun sans preuve issue d’un second jeu.
