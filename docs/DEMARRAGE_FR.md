# Démarrage pas à pas (Home Assistant)

Ce tutoriel installe solarprio dans Home Assistant et le teste **sans risque**. Le logiciel est en version alpha : il a
été testé avec des capteurs et des appareils simulés, jamais sur une vraie installation. Lisez la section *Sécurité* du
[README](../README.md) avant de lui confier du matériel réel.

## 1. Installer

Prérequis : [HACS](https://hacs.xyz) installé, Home Assistant 2026.2 ou plus récent.

1. Cliquez sur le bouton « Open your Home Assistant instance » du [README](../README.md#home-assistant-hacs-custom-repository).
   Il ouvre le dépôt dans **votre** Home Assistant (il demande l'adresse de votre instance la première fois ; selon
   des retours d'utilisateurs, `default_config:` ou `my:` doit être dans votre configuration). Si le bouton ne
   fonctionne pas, faites à la main : HACS > menu (trois points) > **Dépôts personnalisés** > ajoutez `https://github.com/Melvilh/solarprio`,
   type **Intégration**.
2. **Télécharger**, puis **redémarrez** Home Assistant.
3. *Paramètres > Appareils et services > Ajouter une intégration* > cherchez **solarprio**.

## 2. Configurer la mesure

Il faut un capteur de **puissance** (en W ou kW) du compteur, pas un compteur d'énergie (kWh).

- Mode **export** : un seul capteur de puissance réseau. Si votre tableau de bord Énergie en a un, il est déjà
  proposé, avec « mon compteur indique le soutirage en positif » coché (le tableau Énergie compte le soutirage en positif).
  Sinon, choisissez le vôtre et cochez la case si votre capteur est positif quand vous **soutirez**.
- Mode **production** : un capteur de production et un capteur de consommation totale de la maison.
- Réglages : période de contrôle (5 s), mesure considérée comme perdue après (60 s), comportement si la mesure est
  perdue (**éteindre**, recommandé), marge d'injection (voir plus bas), budget de puissance en heures creuses.

**Vérifiez le signe** : avec du soleil et peu de consommation, le capteur doit indiquer une injection. Un mauvais signe
fait croire au logiciel qu'il n'y a jamais de surplus (ou toujours).

## 3. Ajouter un premier appareil de test

*solarprio > Configurer > Ajouter un appareil*. Pour un premier essai, prenez une charge **peu risquée** (une prise
commandée avec une lampe ou un petit radiateur), pas votre chauffe-eau.

- Type **on/off** : l'entité (un `switch`), sa puissance, la priorité (1 = servi en premier).
- Il démarre quand le surplus atteint sa puissance + la « marge de démarrage », et s'arrête quand il passe sous sa
  puissance − la tolérance. Les durées minimales de marche et d'arrêt évitent de claquer le relais.
- Un capteur de **puissance mesurée** (facultatif, recommandé) permet de libérer le surplus quand l'appareil consomme
  moins que prévu.

Dans le panneau, *Ajouter un appareil* propose d'abord des **modèles prêts à l'emploi** (chauffe-eau, borne Victron…) qui
préremplissent les réglages usuels : il ne reste qu'à choisir les entités (liste avec recherche, comme partout dans Home
Assistant). Chaque modèle de marque indique ce qui a été vérifié ; voir [PROFILES.md](PROFILES.md) pour en ajouter.

Vous pouvez aussi tout faire **depuis le panneau solarprio** de la barre latérale : *Ajouter un appareil*, le crayon pour
modifier, la corbeille pour supprimer, et *Réglages* pour la mesure et la sécurité (période de contrôle, délai avant
« mesure perdue », marge d'injection…). Chaque enregistrement recharge l'intégration : les charges sont éteintes un
instant, le temps d'appliquer les nouveaux réglages.

Les appareils déjà suivis dans le tableau Énergie peuvent être importés d'un coup (*Importer des appareils du tableau
Énergie*) ; *Copier un appareil* évite de tout ressaisir pour plusieurs appareils identiques.

## 4. Observer

Si le panneau affiche **« Mesure perdue : appareils éteints »**, solarprio n'a pas pu lire le capteur de mesure et, par
sécurité, il a éteint les appareils. La ligne en dessous donne la raison exacte : capteur `indisponible`, **pas de mise à
jour depuis plus de N secondes** (réglage « Mesure considérée comme perdue après », 60 s par défaut ; un capteur qui
ne change pas de valeur peut sembler « vieux »), ou valeur non numérique. Vérifiez ce capteur dans *Outils de
développement > États*, puis ajustez le délai dans *Réglages* si besoin.


- Le panneau **solarprio** apparaît dans la barre latérale (administrateurs). Glissez-déposez les lignes pour changer
  la priorité : rien n'est éteint par ce geste.
- Entités créées : `sensor.solarprio_available_power`, `sensor.solarprio_routed_power`, `sensor.solarprio_status`, une
  commande par appareil (`sensor.solarprio_<appareil>_command`) et l'interrupteur `switch.solarprio_routing`.
- **Interrupteur de routage** : l'éteindre met tous les appareils à 0 immédiatement. Gardez-le sous la main.
- Pour voir ce qui se passe, dans `configuration.yaml` :

  ```yaml
  logger:
    logs:
      custom_components.solarprio: debug
  ```

## 5. Aller plus loin

- **Marge d'injection** : quelques dizaines de watts laissés non routés évitent que le bruit de mesure se transforme en
  soutirage. Commencez à 50-100 W et ajustez en observant votre compteur.
- **Régulation centralisée** (températures, sécurité sanitaire, plafond d'abonnement, montée progressive, coupure d'urgence) :
  [REGULATION.md](REGULATION.md). Le routeur n'est plus qu'un actionneur ; *Ajouter un appareil* propose des **modèles
  prêts à l'emploi** pour un chauffe-eau.
- **Chauffe-eau avec routeur ESPHome** : [WATER_HEATER_EXAMPLE.md](WATER_HEATER_EXAMPLE.md) et [ESPHOME_ROUTER.md](ESPHOME_ROUTER.md).
- **Tâches informatiques** (calculs lourds, sauvegardes déplaçables) : une catégorie à part qui n'envoie qu'un signal « go »,
  jamais une coupure de courant : [TASKS.md](TASKS.md). N'utilisez jamais une charge tout-ou-rien pour un ordinateur ou un serveur.
- **Heures creuses** (chauffe jusqu'à ce que l'appareil ne consomme plus), avec des plages horaires **ou** une entité
  qui indique les heures creuses (la période tarifaire du Linky, par exemple) : [OFFPEAK.md](OFFPEAK.md).
- **Plusieurs appareils, bornes à contacteur, entreprise** : [MANY_DEVICES.md](MANY_DEVICES.md).
- **Sans Home Assistant (Docker)** : [README](../README.md#standalone-docker-no-home-assistant) et `config.example.toml` ;
  pour une marque précise, écrivez `profile = "victron-evcs"` (voir [PROFILES.md](PROFILES.md)).
- **Ajouter votre matériel** (profil, recette, adaptateur) : [ADDING_COMPATIBILITY.md](ADDING_COMPATIBILITY.md).

## 6. Désinstaller

Supprimez l'intégration (*Paramètres > Appareils et services > solarprio > Supprimer*) : les appareils sont mis à 0 à
la fermeture. Puis supprimez le dépôt dans HACS si vous le souhaitez.

## Problèmes

Ouvrez une [issue](https://github.com/Melvilh/solarprio/issues) en précisant la version de Home Assistant, la
configuration (sans mot de passe) et les journaux avec le niveau `debug` ci-dessus.
