"""Choix de la source de vols, avec repli systématique sur la démonstration.

Trois sources possibles, sélectionnées par ``FOURNISSEUR_VOLS`` :

- ``duffel``  : contenu GDS, NDC et une partie des low-cost ; expose le prix
  des services annexes (bagages) — c'est la source la plus complète pour un
  moteur de surcoûts ;
- ``amadeus`` : compagnies traditionnelles, franchises et tarification bagages ;
- ``demo``    : vols fictifs, sans aucune clé.

En ``auto`` (défaut), on prend la première source configurée dans cet ordre.
Si elle échoue ou ne renvoie rien, on retombe sur la démonstration avec un
avertissement affiché : le voyageur doit toujours savoir ce qu'il regarde.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

from ..modeles import OptionsVoyage, Vol
from . import amadeus, demo, duffel

_LOG = logging.getLogger(__name__)

_DUREE_CACHE = int(os.environ.get("VOLS_CACHE_SECONDES", "300"))
_cache: dict[tuple, tuple[float, list[Vol]]] = {}
_verrou = threading.Lock()

# Par ordre de préférence : la meilleure couverture des suppléments d'abord.
_SOURCES = {"duffel": duffel, "amadeus": amadeus}

_NOMS = {"duffel": "Duffel", "amadeus": "Amadeus", "demo": "démonstration"}


class ResultatRecherche:
    def __init__(self, vols: list[Vol], source: str, avertissement: str | None = None):
        self.vols = vols
        self.source = source  # "duffel", "amadeus" ou "demo"
        self.avertissement = avertissement

    @property
    def temps_reel(self) -> bool:
        return self.source != "demo"

    @property
    def nom_source(self) -> str:
        return _NOMS.get(self.source, self.source)


def source_active() -> str:
    """Nom de la source qui serait interrogée maintenant."""
    choix = os.environ.get("FOURNISSEUR_VOLS", "auto").lower()
    if choix in _SOURCES:
        return choix if _SOURCES[choix].configure() else "demo"
    if choix == "demo":
        return "demo"
    for nom, module in _SOURCES.items():
        if module.configure():
            return nom
    return "demo"


def rechercher(origine: str, destination: str, jour: date,
               options: OptionsVoyage) -> ResultatRecherche:
    # La composition des voyageurs entre dans la clé : un tarif enfant n'est
    # pas un tarif adulte, le résultat mis en cache n'est pas interchangeable.
    cle = (origine.upper(), destination.upper(), jour.isoformat(),
           options.adultes, tuple(options.enfants), options.bebes)
    with _verrou:
        entree = _cache.get(cle)
        if entree and time.time() - entree[0] < _DUREE_CACHE:
            vols = entree[1]
            return ResultatRecherche(vols, vols[0].source if vols else "demo")

    avertissement = None
    nom = source_active()
    if nom in _SOURCES:
        module = _SOURCES[nom]
        try:
            vols = module.rechercher(origine, destination, jour, options)
            if vols:
                _memoriser(cle, vols)
                return ResultatRecherche(vols, nom)
            avertissement = (
                f"Aucun vol sur cette liaison à cette date chez {_NOMS[nom]} — "
                "affichage de vols de démonstration."
            )
        except Exception as erreur:  # panne réseau, quota, format inattendu…
            _LOG.warning("%s indisponible, repli sur la démonstration : %s", _NOMS[nom], erreur)
            avertissement = (
                "La connexion aux vols en temps réel a échoué — affichage de "
                "vols de démonstration."
            )

    vols = demo.rechercher(origine, destination, jour, options)
    _memoriser(cle, vols)
    return ResultatRecherche(vols, "demo", avertissement)


def _memoriser(cle: tuple, vols: list[Vol]) -> None:
    with _verrou:
        _cache[cle] = (time.time(), vols)
        if len(_cache) > 200:  # purge simple des entrées les plus anciennes
            for vieille in sorted(_cache, key=lambda k: _cache[k][0])[:50]:
                _cache.pop(vieille, None)


def recherche_aeroports_disponible() -> bool:
    """Une source sait-elle traduire un nom de ville en code d'aéroport ?"""
    return duffel.configure() or amadeus.configure()


def chercher_aeroports(mot_cle: str) -> list[dict]:
    """Recherche d'aéroport par nom de ville.

    Duffel d'abord (son offre de lieux est ouverte avec le même jeton que les
    vols), Amadeus en secours. Un échec ne remonte jamais à l'interface :
    l'autocomplétion est un confort, pas une condition pour chercher un vol.
    """
    for module in (duffel, amadeus):
        if not module.configure():
            continue
        try:
            resultats = module.chercher_aeroports(mot_cle)
        except Exception as erreur:
            _LOG.info("Recherche d'aéroport indisponible via %s : %s",
                      _NOMS.get(module.__name__.rsplit(".", 1)[-1], module.__name__), erreur)
            continue
        if resultats:
            return resultats
    return []
