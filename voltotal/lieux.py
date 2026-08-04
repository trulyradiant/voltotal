"""Recherche de lieux : « paris » → la ville, puis chacun de ses aéroports.

Deux sources complémentaires :

- la **base locale** (`data/aeroports.json`), qui répond instantanément, sans
  clé ni réseau, et couvre les villes usuelles au départ de France ;
- **Duffel**, qui complète pour tout le reste quand il est configuré.

Le résultat est toujours groupé par ville. Une ville n'expose un choix
« tous les aéroports » que si un vrai code IATA de ville existe (PAR, LON,
MIL…) : lui seul est accepté par les moteurs de recherche de vols. Pour
Barcelone ou Bruxelles, qui n'en ont pas, on ne propose que les aéroports.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

_FICHIER = Path(__file__).parent / "data" / "aeroports.json"


def _sans_accent(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


class BaseLieux:
    def __init__(self, chemin: Path = _FICHIER):
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        self.villes: list[dict] = donnees["villes"]
        # Index de recherche : ville, pays, noms et codes d'aéroports.
        self._index = [
            (
                " ".join(
                    [_sans_accent(v["nom"]), _sans_accent(v.get("pays", ""))]
                    + [_sans_accent(a["nom"]) + " " + a["code"].lower() for a in v["aeroports"]]
                    + ([v["code_tous"].lower()] if v.get("code_tous") else [])
                ),
                _sans_accent(v["nom"]),
                v,
            )
            for v in self.villes
        ]

    def rechercher(self, mot_cle: str, limite: int = 6) -> list[dict]:
        recherche = _sans_accent(mot_cle.strip())
        if not recherche:
            return []
        trouves = []
        for index, nom_ville, ville in self._index:
            if recherche not in index:
                continue
            # Une ville dont le nom commence par la saisie passe devant.
            priorite = 0 if nom_ville.startswith(recherche) else 1
            trouves.append((priorite, ville))
        trouves.sort(key=lambda couple: couple[0])
        return [_formater(ville) for _, ville in trouves[:limite]]


def _formater(ville: dict) -> dict:
    return {
        "ville": ville["nom"],
        "pays": ville.get("pays", ""),
        "code_tous": ville.get("code_tous"),
        "aeroports": [
            {"code": a["code"], "nom": a["nom"]} for a in ville["aeroports"]
        ],
    }


def fusionner(locaux: list[dict], distants: list[dict], limite: int = 8) -> list[dict]:
    """Complète les résultats locaux par ceux de l'API, sans doublon.

    Les entrées locales sont prioritaires : leurs libellés sont en français
    et vérifiés à la main, là où l'API renvoie des noms bruts.
    """
    connus = {ville["ville"].lower() for ville in locaux}
    codes_connus = {a["code"] for ville in locaux for a in ville["aeroports"]}
    resultat = list(locaux)
    for ville in distants:
        if ville["ville"].lower() in connus:
            continue
        if all(a["code"] in codes_connus for a in ville["aeroports"]):
            continue
        resultat.append(ville)
        if len(resultat) >= limite:
            break
    return resultat[:limite]
