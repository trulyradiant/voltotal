# VolTotal — recherche de vols au prix réel, surcoûts pré-calculés

Les comparateurs classiques trient par **prix d'appel** : 19 € chez une
low-cost… puis 12 € de bagage cabine, 25 € de soute, 8 € de siège, 55 € si
vous vous enregistrez à l'aéroport. VolTotal fait l'inverse : vous dites ce
que vous emportez vraiment, et **chaque vol est affiché et trié à son prix
total tout compris**, calculé à l'avance. Aucune mauvaise surprise.

## Comment ça marche

1. Vous indiquez le trajet, la date, le nombre de passagers **et vos
   options** : bagage cabine, bagages en soute, choix du siège,
   enregistrement à l'aéroport.
2. Le moteur récupère les vols disponibles.
3. Pour chaque vol, la **grille de frais de la compagnie**
   (`data/frais_compagnies.json` : Ryanair, easyJet, Vueling, Transavia,
   Wizz Air, Volotea, Air France, KLM, Lufthansa, Iberia, TAP…) est
   appliquée à vos options.
4. Les résultats sont triés par **prix réel total**, avec le détail des
   frais et le prix d'appel barré. Une compagnie absente de la grille reçoit
   une **estimation prudente** (frais par défaut majorés), signalée comme
   telle.

## Essayer en local

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # celui à la racine du dépôt
.venv/bin/python -m flightsearch.wsgi
```

Ouvrez http://127.0.0.1:5001 — sans configuration, l'app tourne en **mode
démonstration** : vols fictifs mais réalistes et stables (même recherche →
mêmes résultats), surcoûts calculés avec la vraie grille.

## Vols réels (API Amadeus, gratuite)

Créez un compte Self-Service sur https://developers.amadeus.com puis :

```
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
```

Avec ces deux variables, la recherche interroge l'environnement de test
Amadeus (vraies compagnies, vrais horaires, prix indicatifs) au lieu du mode
démonstration.

## Déploiement (Railway, comme MailGuard)

Créez un second service sur le même dépôt avec la commande de démarrage :

```
gunicorn flightsearch.wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4
```

## Tests

```
python -m unittest discover flightsearch
```

## Limites connues (MVP)

- Grille de frais **indicative** (par passager, par trajet) : les montants
  réels varient selon la route, la saison et la franchise choisie — la date
  de dernière mise à jour est affichée sous les résultats.
- Aller simple uniquement pour l'instant ; pas encore de réservation, le
  moteur compare et calcule.
- L'environnement de test Amadeus couvre un sous-ensemble de routes.
