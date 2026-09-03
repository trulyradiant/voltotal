"""Vols de démonstration : réalistes, stables, sans aucune clé d'API.

Une même recherche redonne toujours les mêmes vols (tirage semé par le
trajet et la date), pour pouvoir comparer l'effet des options sans que les
prix bougent sous les doigts.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta

from ..modeles import OptionsVoyage, Vol

_COMPAGNIES = {
    "FR": "Ryanair", "U2": "easyJet", "VY": "Vueling", "W6": "Wizz Air",
    "TO": "Transavia France", "V7": "Volotea", "AF": "Air France",
    "KL": "KLM", "LH": "Lufthansa", "IB": "Iberia",
}
_LOW_COST = {"FR", "U2", "VY", "TO", "V7", "W6"}


def rechercher(origine: str, destination: str, jour: date, options: OptionsVoyage,
               tarifs_bagages: bool = True) -> list[Vol]:
    graine = f"{origine.upper()}-{destination.upper()}-{jour.isoformat()}"
    alea = random.Random(hashlib.sha256(graine.encode()).hexdigest())

    codes = list(_COMPAGNIES)
    duree_base = 60 + alea.randint(0, 180)
    vols = []
    for _ in range(alea.randint(6, 9)):
        code = alea.choice(codes)
        depart = datetime.combine(jour, datetime.min.time()) + timedelta(
            hours=6 + alea.randint(0, 16), minutes=alea.choice([0, 15, 30, 45])
        )
        escales = 0 if alea.random() < 0.75 else 1
        duree = duree_base + alea.randint(-15, 25) + escales * (60 + alea.randint(0, 90))
        low_cost = code in _LOW_COST
        prix = round((18 if low_cost else 55) + alea.random() * (90 if low_cost else 160), 2)
        vols.append(
            Vol(
                compagnie=code,
                nom_compagnie=_COMPAGNIES[code],
                numero=f"{code}{alea.randint(1000, 9999)}",
                origine=origine.upper(),
                destination=destination.upper(),
                depart=depart,
                arrivee=depart + timedelta(minutes=duree),
                escales=escales,
                prix_affiche=prix,
                source="demo",
            )
        )
    vols.sort(key=lambda v: v.prix_affiche)
    return vols
