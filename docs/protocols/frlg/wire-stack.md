# Pile filaire FRLG — état de spécification

La première implémentation cible la variante PIA v16 (PIA 6.32–7.2) observée
dans le périmètre FRLG. Elle rejette les versions inconnues au lieu de tenter
une compatibilité implicite.

1. UDP/12345 circule sur le transport LDN établi par ce dépôt.
2. L’en-tête PIA v16 est big-endian : magic `32 AB 98 64`, flags/version,
   flags de transport/padding, IDs variables destination/source, packet ID,
   longueur de footer, nonce de huit octets, tag GCM tronqué à huit octets.
3. Les messages PIA v16 transportent les champs présents signalés par un
   bitmap; les champs absents héritent du message précédent. Le padding final
   canonique éventuel est constitué d’octets `0xff`; l’alignement par zéros
   concerne l’ancien codec v11, pas les tuiles v16 ciblées ici.
4. LDN PIA dérive une clé AES à partir du SSID et de la clé spécifique au jeu;
   le nonce GCM contient `network_id XOR IPv4_source` et le nonce filaire.
5. Le canal fiable, puis les trames GBA/RFU et enfin la machine d’échange,
   restent privés au plugin FRLG.

## Enveloppe émulateur et RFU

Les trames GBA commencent par `0x57`, suivies du type ASCII et d’une taille
`u16le`. `C` ouvre le lien follower et `A` en confirme l’acceptation côté
émulateur; cette acceptation ne vaut pas encore entrée dans le salon. Le
contrôle `G` observé (corps de quatre octets nul dans une capture locale) est
préservé mais n’entraîne aucune réponse ni transition spéculative. Le premier
LLSF UNI du host prouve seulement la fin de NI : le jalon métier
`ROOM_ENTERED` attend le premier `SEND_HELD_KEYS`, émis lorsque le leader est
assis dans la salle. Le follower émet les slots `T` avec `timestamp:u32le`, un octet nul, la
taille du slot à l’offset 5, puis deux octets nuls. Le host les émet avec la
taille à l’offset 4 puis trois octets nuls. Les slots sont arrondis à quatre
octets et les timestamps hôte reçoivent au plus un ACK `K` chacun.

Un slot RFU UNI du follower est un LLSF enfant de deux octets (`state=4`,
taille 14) suivi de sept mots `u16le`. Les blocs utilisent `0x8800` (init) et
`0x8900` (fragment de 12 octets); le réassembleur accepte doublons et ordre
variable. Les barrières `0x6600` et `0x5f00` sont répondus explicitement par
le follower afin de permettre une sortie gracieuse.

Après `A`, le follower émet son NI GameData à raison d’une tuile par VBlank;
PIA Reliable assure la livraison de ces tuiles. Les ACK parent associés à cet
envoi ne transforment donc pas NI en protocole stop-and-wait. Inversement, un
NI émis par le host (`ack=0`) reçoit une unique tuile enfant miroir `ack=1`
pour chaque état/index/phase distinct. Le follower n’émet aucun UNI avant le
premier LLSF UNI du host.

Les ACK `K`, le slot `T` courant et l’ACK cumulatif/sélectif sont regroupés
dans le même datagramme PIA lorsque leur échéance coïncide. La machine NI/bloc
n’avance pas si la fenêtre Reliable est pleine : une VBlank historique ne doit
jamais être mise en attente puis libérée avec plusieurs autres slots dans une
seule rafale, car le pont émulateur ne consomme qu’un slot enfant par VBlank.

Les formats PIA proviennent de la documentation publique NintendoClients. Les
constantes FRLG non publiques ne seront ajoutées qu’accompagnées d’une capture
expurgée ou d’un vecteur synthétique vérifiable.
