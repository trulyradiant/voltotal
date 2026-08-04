# VolTotal — recherche de vols au prix réel, surcoûts pré-calculés

Les comparateurs classiques trient par **prix d'appel** : 19 € chez une
low-cost… puis 12 € de bagage cabine, 25 € de soute, 8 € de siège, 55 € si
vous vous enregistrez à l'aéroport. VolTotal fait l'inverse : vous dites ce
que vous emportez vraiment, et **chaque vol est affiché et trié à son prix
total tout compris**, calculé à l'avance.

## Comment ça marche

1. Vous indiquez le trajet, les dates (aller simple ou aller-retour), le
   nombre de passagers **et vos options** : bagage cabine, bagages en soute,
   choix du siège, enregistrement à l'aéroport.
2. Le serveur cherche les vols — **en temps réel** (Duffel ou Amadeus) si des
   clés sont configurées, sinon des vols de démonstration.
3. Pour chaque vol, il détermine les tarifs applicables (voir « D'où viennent
   les prix » ci-dessous) et les renvoie au navigateur.
4. L'interface affiche **le total tout compris en haut de l'écran**, puis les
   deux listes triées par prix réel. Cocher une option recalcule tout
   instantanément, sans nouvel appel au serveur.

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
navigateur ou un téléphone, uniquement en mode démonstration.

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

### Amadeus

1. Créez un compte Self-Service sur https://developers.amadeus.com.
2. Créez une application et copiez la **API Key** et l'**API Secret**.
3. Renseignez `AMADEUS_CLIENT_ID` et `AMADEUS_CLIENT_SECRET`.

L'environnement **test** (par défaut) est gratuit mais ne couvre qu'une
partie des vols et affiche des prix indicatifs. Passer en production
(`AMADEUS_ENV=production`) demande un dossier validé et une facturation.

Amadeus fournit aussi la **recherche d'aéroport par nom de ville**, utilisée
pour l'autocomplétion des champs de départ et d'arrivée.

### Ce que chaque source couvre

| | Duffel | Amadeus | Démonstration |
|---|---|---|---|
| Compagnies traditionnelles | ✅ | ✅ | fictif |
| Low-cost (Ryanair, easyJet, Wizz) | ✅ partiel, selon leur catalogue | ❌ non distribuées | fictif |
| Franchise bagage incluse | ✅ | ✅ | — |
| Prix réel du bagage en soute | ✅ services annexes | ✅ tarification `include=bags` | — |
| Prix du choix de siège | ❌ | ❌ | — |
| Enregistrement à l'aéroport | ❌ | ❌ | — |
| Recherche d'aéroport par ville | ❌ | ✅ | — |

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
| `modeles.py` | Objets partagés : `Vol`, `OptionsVoyage`, `Surcouts` |
| `fournisseurs/duffel.py` | Connecteur Duffel : vols, franchises, services annexes (bagages) |
| `fournisseurs/amadeus.py` | Connecteur Amadeus : vols, franchises, tarifs bagages, recherche d'aéroports |
| `fournisseurs/demo.py` | Générateur de vols de démonstration, déterministe |
| `fournisseurs/__init__.py` | Choix de la source, cache mémoire, repli en cas de panne |
| `surcouts.py` | Grille interne et arbitrage entre tarif publié et estimation |
| `app.py` | Routes Flask : page, `/api/vols`, `/api/aeroports`, `/sources`, `/sante` |
| `templates/index.html` | Interface mobile (calcul instantané côté navigateur) |
| `demo_statique.html` | Version autonome sans serveur |

## Tests

```
python -m unittest discover -t . -s voltotal
```

27 tests, sans aucun appel réseau : les réponses des API sont simulées.

## Limites connues

- Grille de frais interne **indicative**, maintenue à la main.
- Pas de réservation : le moteur compare et calcule.
- Aller-retour traité comme deux allers simples (pas de tarif combiné).
