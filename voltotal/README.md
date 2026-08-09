# VolTotal — recherche de vols au prix réel, surcoûts pré-calculés

Les comparateurs classiques trient par **prix d'appel** : 19 € chez une
low-cost… puis 12 € de bagage cabine, 25 € de soute, 8 € de siège, 55 € si
vous vous enregistrez à l'aéroport. VolTotal fait l'inverse : vous dites ce
que vous emportez vraiment, et **chaque vol est affiché et trié à son prix
total tout compris**, calculé à l'avance.

## Comment ça marche

1. Vous tapez une **ville** (« paris », « lond ») : la liste propose la ville
   et chacun de ses aéroports. Quand un code IATA de ville existe (PAR, LON,
   MIL…), une entrée **« tous les aéroports »** cherche sur l'ensemble d'un
   coup.
2. Vous déclarez **qui voyage** — adultes, enfants avec leur âge, bébés sur
   les genoux — **et ce que vous emportez** : bagage cabine, bagages en soute,
   choix du siège, enregistrement à l'aéroport, équipement sportif (skis,
   golf, vélo, surf).
3. Le serveur cherche les vols — **en temps réel** (Duffel ou Amadeus) si des
   clés sont configurées, sinon des vols de démonstration.
4. Pour chaque vol, il détermine les tarifs applicables (voir « D'où viennent
   les prix » ci-dessous) et les renvoie au navigateur.
5. L'interface affiche **le total tout compris en haut de l'écran**, une
   **bande de prix par jour** autour de vos dates, puis les deux listes triées
   par prix réel. Modifier une option recalcule tout instantanément, sans
   nouvel appel au serveur.

## Comment les suppléments sont comptés

| Poste | Unité |
|---|---|
| Bagage cabine, bagages en soute, choix du siège, enregistrement | par **passager payant** et par trajet |
| Équipement sportif (skis, golf, vélo, surf) | **à la pièce** et par trajet — une housse à skis coûte pareil pour un skieur ou quatre |

Un **bébé de moins de 2 ans** voyage sur les genoux : ni siège, ni franchise
bagage. Il n'entre donc pas dans le calcul des suppléments. Les **enfants de
2 à 11 ans** comptent comme des passagers payants, et leur âge est transmis
au fournisseur, qui applique le tarif enfant de la compagnie.

## Bande de prix par jour

Sous chaque date, une bande montre le **prix réel le moins cher** de chaque
jour, options comprises, le plus bas en vert. Toucher un jour déplace la
recherche.

C'est une recherche par jour : coûteux en quota d'API. La fenêtre est donc
volontairement étroite (`CALENDRIER_JOURS`, ±3 jours par défaut) et partage
le cache des recherches normales. Mettez-la à `0` pour n'afficher que le jour
choisi.

## D'où viennent les prix

Deux sources, dans cet ordre de confiance :

| Source | Ce qu'elle couvre | Affichage |
|---|---|---|
| **Tarif de la compagnie** (API) | Franchise cabine et soute incluse dans le billet, prix réel d'un bagage en soute pour cette offre précise | « tarif compagnie », total marqué ✔ |
| **Grille interne** (`data/frais_compagnies.json`) | Tout le reste : choix du siège, enregistrement à l'aéroport, et les bagages quand la compagnie ne publie rien | « estimation » |

Une compagnie absente de la grille reçoit une **estimation prudente** (frais
par défaut majorés), signalée comme telle. La date de dernière mise à jour de
la grille est affichée en bas de page.

## Essayer en local

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # celui à la racine du dépôt
.venv/bin/python -m voltotal.wsgi
```

Ouvrez http://127.0.0.1:5001 — sans configuration, l'app tourne en **mode
démonstration** : vols fictifs mais réalistes et stables (même recherche →
mêmes résultats), surcoûts calculés avec la grille interne.

Le fichier `demo_statique.html` est une version autonome de l'interface
(HTML + JavaScript, sans serveur) : elle s'ouvre directement dans un
navigateur ou un téléphone, uniquement en mode démonstration. C'est un
**instantané simplifié**, figé à une version antérieure : il n'a ni la
saisie par ville, ni les voyageurs détaillés, ni la bande de prix par jour,
qui demandent toutes un serveur.

## Habillage

L'interface suit les conventions de **Material Design**, la langue visuelle
de Google Flights : surfaces blanches posées sur un fond gris clair, ombres
douces plutôt que bordures marquées, bleu `#1a73e8` pour l'action, vert
`#188038` réservé au prix, et des résultats en **liste plate séparée par des
filets** plutôt qu'en pile de cartes. Roboto est chargée depuis Google Fonts,
avec repli sur la police système (Roboto nativement sur Android) si la
requête échoue.

Il s'agit d'une reprise des conventions publiques de Material Design, pas
d'une copie de la marque : aucun logo ni élément d'identité Google n'est
utilisé.

## Brancher les vols en temps réel

Deux fournisseurs sont pris en charge. En `FOURNISSEUR_VOLS=auto` (défaut),
**Duffel est préféré s'il est configuré**, sinon Amadeus, sinon la
démonstration. `/sources` indique laquelle est active.

### Duffel — recommandé

C'est le fournisseur le plus intéressant ici : il distribue du contenu GDS,
NDC **et une partie des compagnies low-cost**, et son appel « available
services » renvoie le prix réel du bagage en soute proposé sur l'offre.

1. Créez un compte sur https://duffel.com (libre-service, sans démarche
   commerciale) et copiez le jeton de test.
2. Renseignez `DUFFEL_TOKEN=duffel_test_...`

⚠️ **En mode test, Duffel répond avec une compagnie fictive (« Duffel
Airways »)** : c'est utile pour valider toute la chaîne technique, pas pour
comparer de vrais prix. Le contenu réel des compagnies demande un compte
validé par Duffel et un jeton `duffel_live_`.

**Passer en réel** : remplacez la *valeur* de `DUFFEL_TOKEN` par le jeton
`duffel_live_…`. Le nom de la variable ne change pas, le code non plus.
`/sources` renvoie alors `"duffel_mode": "live"` — c'est la seule façon de
vérifier la bascule, les deux jetons se ressemblant beaucoup.

### Amadeus — optionnel, et peut-être fermé

> ⚠️ L'offre Self-Service d'Amadeus ne semble plus ouverte aux nouvelles
> inscriptions (constaté en août 2026). Le connecteur est conservé et
> fonctionne pour qui possède déjà des clés, mais **Duffel seul suffit** :
> il couvre désormais les vols *et* la recherche d'aéroports.

1. Créez un compte Self-Service sur https://developers.amadeus.com.
2. Créez une application et copiez la **API Key** et l'**API Secret**.
3. Renseignez `AMADEUS_CLIENT_ID` et `AMADEUS_CLIENT_SECRET`.

L'environnement **test** (par défaut) est gratuit mais ne couvre qu'une
partie des vols et affiche des prix indicatifs. Passer en production
(`AMADEUS_ENV=production`) demande un dossier validé et une facturation.

La saisie par nom de ville repose d'abord sur une **base locale**
(`data/aeroports.json`) qui répond sans réseau ni clé : elle fonctionne donc
même en mode démonstration. Duffel, puis Amadeus, ne font que la compléter
pour les villes absentes de cette base.

### Ce que chaque source couvre

| | Duffel | Amadeus | Démonstration |
|---|---|---|---|
| Compagnies traditionnelles | ✅ | ✅ | fictif |
| Low-cost (Ryanair, easyJet, Wizz) | ✅ partiel, selon leur catalogue | ❌ non distribuées | fictif |
| Franchise bagage incluse | ✅ | ✅ | — |
| Prix réel du bagage en soute | ✅ services annexes | ✅ tarification `include=bags` | — |
| Prix du choix de siège | ❌ | ❌ | — |
| Enregistrement à l'aéroport | ❌ | ❌ | — |
| Recherche d'aéroport par ville | ✅ `/places/suggestions` | ✅ | — |

Aucune API publique ne donne le tarif du **choix de siège** ni de
l'**enregistrement à l'aéroport** : ces deux montants restent estimés par la
grille interne, et l'affichage le signale.

## Déploiement (Railway, comme MailGuard)

Créez un second service sur le même dépôt avec la commande de démarrage :

```
gunicorn voltotal.wsgi:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4
```

Ajoutez `DUFFEL_TOKEN` (et/ou `AMADEUS_CLIENT_ID` + `AMADEUS_CLIENT_SECRET`)
dans les Variables du service pour activer le temps réel. Vérifiez ensuite
`/sources` : il indique la source réellement active.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `modeles.py` | Objets partagés : `Vol`, `OptionsVoyage`, `Surcouts`, équipements |
| `fournisseurs/duffel.py` | Connecteur Duffel : vols, franchises, services annexes (bagages), recherche d'aéroports |
| `fournisseurs/amadeus.py` | Connecteur Amadeus : vols, franchises, tarifs bagages, recherche d'aéroports |
| `fournisseurs/demo.py` | Générateur de vols de démonstration, déterministe |
| `fournisseurs/__init__.py` | Choix de la source, cache mémoire, repli en cas de panne |
| `lieux.py` | Base locale de villes et aéroports, pour la saisie par nom de ville |
| `surcouts.py` | Grille interne et arbitrage entre tarif publié et estimation |
| `app.py` | Routes Flask : page, `/api/vols`, `/api/calendrier`, `/api/aeroports`, `/sources`, `/sante` |
| `templates/index.html` | Interface mobile (calcul instantané côté navigateur) |
| `demo_statique.html` | Version autonome sans serveur |

## Tests

```
python -m unittest discover -t . -s voltotal
```

57 tests, sans aucun appel réseau : les réponses des API sont simulées.

## Limites connues

- Grille de frais interne **indicative**, maintenue à la main.
- Pas de réservation : le moteur compare et calcule.
- Aller-retour traité comme deux allers simples (pas de tarif combiné).
