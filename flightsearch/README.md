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
2. Le serveur cherche les vols — **Amadeus en temps réel** si des clés sont
   configurées, sinon des vols de démonstration.
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
.venv/bin/python -m flightsearch.wsgi
```

Ouvrez http://127.0.0.1:5001 — sans configuration, l'app tourne en **mode
démonstration** : vols fictifs mais réalistes et stables (même recherche →
mêmes résultats), surcoûts calculés avec la grille interne.

Le fichier `demo_statique.html` est une version autonome de l'interface
(HTML + JavaScript, sans serveur) : elle s'ouvre directement dans un
navigateur ou un téléphone, uniquement en mode démonstration.

## Brancher les vols en temps réel (Amadeus, gratuit)

1. Créez un compte Self-Service sur https://developers.amadeus.com.
2. Créez une application dans « My Self-Service Workspace » et copiez la
   **API Key** et l'**API Secret**.
3. Renseignez les variables :

```
AMADEUS_CLIENT_ID=votre_api_key
AMADEUS_CLIENT_SECRET=votre_api_secret
```

Au démarrage suivant, la recherche interroge Amadeus. Vérifiez avec
`/sante` : `"vols_temps_reel": true`.

L'environnement **test** (par défaut) est gratuit mais ne couvre qu'une
partie des vols et affiche des prix indicatifs. Passer en production
(`AMADEUS_ENV=production`) demande un dossier validé par Amadeus et une
facturation à l'appel.

### Ce que cette source couvre — et ne couvre pas

- ✅ Vols, horaires, escales et prix des compagnies **traditionnelles**
  (Air France, KLM, Lufthansa, Iberia, TAP…).
- ✅ Franchise bagage incluse dans le tarif, et **prix réel du bagage en
  soute** pour l'offre consultée (appel de tarification `include=bags`).
- ❌ **Les low-cost pures (Ryanair, easyJet, Wizz Air) ne sont pas
  distribuées par Amadeus** — or ce sont précisément celles qui facturent le
  plus de suppléments. Sur ces compagnies, VolTotal continue d'utiliser sa
  grille interne, et le total est affiché comme une estimation.
- ❌ Aucune API publique ne donne le tarif du **choix de siège** ni de
  l'**enregistrement à l'aéroport** : ces montants restent estimés.

Couvrir les low-cost demanderait un autre fournisseur (Duffel, Kiwi Tequila,
Skyscanner Partners), tous soumis à un accord commercial. C'est la principale
limite à lever pour que l'app tienne complètement sa promesse.

## Déploiement (Railway, comme MailGuard)

Créez un second service sur le même dépôt avec la commande de démarrage :

```
gunicorn flightsearch.wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4
```

Ajoutez `AMADEUS_CLIENT_ID` et `AMADEUS_CLIENT_SECRET` dans les Variables du
service pour activer le temps réel.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `modeles.py` | Objets partagés : `Vol`, `OptionsVoyage`, `Surcouts` |
| `fournisseurs/amadeus.py` | Connecteur API : vols, franchises, tarifs bagages, recherche d'aéroports |
| `fournisseurs/demo.py` | Générateur de vols de démonstration, déterministe |
| `fournisseurs/__init__.py` | Choix de la source, cache mémoire, repli en cas de panne |
| `surcouts.py` | Grille interne et arbitrage entre tarif publié et estimation |
| `app.py` | Routes Flask : page, `/api/vols`, `/api/aeroports`, `/sante` |
| `templates/index.html` | Interface mobile (calcul instantané côté navigateur) |
| `demo_statique.html` | Version autonome sans serveur |

## Tests

```
python -m unittest discover -t . -s flightsearch
```

20 tests, sans aucun appel réseau : les réponses Amadeus sont simulées.

## Limites connues

- Grille de frais interne **indicative**, maintenue à la main.
- Pas de réservation : le moteur compare et calcule.
- Aller-retour traité comme deux allers simples (pas de tarif combiné).
