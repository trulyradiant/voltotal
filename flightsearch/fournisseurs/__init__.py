"""Choix de la source de vols : Amadeus si des clés existent, sinon démo.

Un petit cache mémoire évite de rappeler l'API pour une recherche identique
(le voyageur qui coche « bagage en soute » ne doit pas déclencher un nouvel
appel : les vols n'ont pas changé, seuls les frais se recalculent).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

from ..modeles import Vol
from . import amadeus, demo

_LOG = logging.getLogger(__name__)

_DUREE_CACHE = int(os.environ.get("VOLS_CACHE_SECONDES", "300"))
_cache: dict[tuple, tuple[float, list[Vol]]] = {}
_verrou = threading.Lock()


class ResultatRecherche:
    def __init__(self, vols: list[Vol], source: str, avertissement: str | None = None):
        self.vols = vols
        self.source = source  # "amadeus" ou "demo"
        self.avertissement = avertissement

    @property
    def temps_reel(self) -> bool:
        return self.source == "amadeus"


def rechercher(origine: str, destination: str, jour: date, passagers: int) -> ResultatRecherche:
    cle = (origine.upper(), destination.upper(), jour.isoformat(), passagers)
    with _verrou:
        entree = _cache.get(cle)
        if entree and time.time() - entree[0] < _DUREE_CACHE:
            vols = entree[1]
            return ResultatRecherche(vols, vols[0].source if vols else "demo")

    avertissement = None
    if amadeus.configure():
        try:
            vols = amadeus.rechercher(origine, destination, jour, passagers)
            if vols:
                _memoriser(cle, vols)
                return ResultatRecherche(vols, "amadeus")
            avertissement = (
                "Aucun vol réel sur cette liaison à cette date — affichage de "
                "vols de démonstration."
            )
        except amadeus.ErreurAmadeus as erreur:
            _LOG.warning("Amadeus indisponible, repli sur la démonstration : %s", erreur)
            avertissement = (
                "La connexion aux vols en temps réel a échoué — affichage de "
                "vols de démonstration."
            )

    vols = demo.rechercher(origine, destination, jour, passagers)
    _memoriser(cle, vols)
    return ResultatRecherche(vols, "demo", avertissement)


def _memoriser(cle: tuple, vols: list[Vol]) -> None:
    with _verrou:
        _cache[cle] = (time.time(), vols)
        if len(_cache) > 200:  # purge simple des entrées les plus anciennes
            for vieille in sorted(_cache, key=lambda k: _cache[k][0])[:50]:
                _cache.pop(vieille, None)


def chercher_aeroports(mot_cle: str) -> list[dict]:
    """Recherche d'aéroport par nom de ville, quand l'API est configurée."""
    if not amadeus.configure():
        return []
    try:
        return amadeus.chercher_aeroports(mot_cle)
    except amadeus.ErreurAmadeus as erreur:
        _LOG.info("Recherche d'aéroport indisponible : %s", erreur)
        return []
