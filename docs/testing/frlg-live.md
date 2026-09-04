# Validation matérielle FRLG — Intel AX200

Ce protocole est volontairement manuel : il ne doit jamais être exécuté en
parallèle d’un autre client privilégié.

1. Vérifier qu’aucun client LDN privilégié résiduel ne possède `ldnclient`; si
   une session est en cours, ne pas la tuer depuis un autre outil.
2. Créer un salon Leader FRLG sur la Switch, préparer le moniteur AX200, puis
   noter version du noyau, firmware, version du projet et heure de début dans
   un journal local ignoré par Git.
3. Effectuer trois sessions consécutives sans modifier les réglages : FireRed,
   échange séquentiel de deux Pokémon, puis LeafGreen. Pour chacune, noter les
   jalons LDN, PIA, entrée de salon, commit, sauvegarde, sortie et nettoyage.
4. Valider chaque `.pk3` reçu : 100 octets, checksum Gen III valide et export
   uniquement après commit. Ne conserver dans Git que compteurs/durées expurgés.
5. En cas d’échec, conserver la capture sous `captures/` (mode 0600), rejouer
   une version synthétique hors ligne et classer le dernier jalon avant toute
   modification du cœur LDN.

Les captures, SSID, MAC, nom de dresseur, passphrase, prod.keys et Pokémon
personnels ne doivent jamais être ajoutés au dépôt.
