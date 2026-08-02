"""Recherche de vols : API Amadeus si des clés sont fournies, sinon démo.

- Avec ``AMADEUS_CLIENT_ID`` / ``AMADEUS_CLIENT_SECRET`` (offre Self-Service
  gratuite : https://developers.amadeus.com), la recherche interroge de vrais
  vols (environnement de test Amadeus).
- Sans clés, un générateur de démonstration produit des vols réalistes et
  stables (même recherche → mêmes résultats) pour essayer l'interface.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass
class Vol:
    compagnie: str  # code IATA, ex. "FR"
    numero: str
    origine: str
    destination: str
    depart: datetime
    arrivee: datetime
    escales: int
    prix_affiche: float  # le prix d'appel, par passager
    source: str  # "amadeus" ou "demo"

    @property
    def duree(self) -> str:
        minutes = int((self.arrivee - self.depart).total_seconds() // 60)
        return f"{minutes // 60}h{minutes % 60:02d}"


def rechercher(origine: str, destination: str, jour: date, passagers: int) -> list[Vol]:
    if os.environ.get("AMADEUS_CLIENT_ID") and os.environ.get("AMADEUS_CLIENT_SECRET"):
        return _rechercher_amadeus(origine, destination, jour, passagers)
    return _rechercher_demo(origine, destination, jour)


# --- Démo -----------------------------------------------------------------

_COMPAGNIES_DEMO = ["FR", "U2", "VY", "TO", "V7", "AF", "KL", "LH", "IB", "W6"]


def _rechercher_demo(origine: str, destination: str, jour: date) -> list[Vol]:
    """Vols fictifs mais plausibles, déterministes pour une recherche donnée."""
    graine = f"{origine}-{destination}-{jour.isoformat()}"
    alea = random.Random(hashlib.sha256(graine.encode()).hexdigest())

    # Durée de vol plausible dérivée de la paire d'aéroports (1h à 4h).
    duree_base = 60 + alea.randint(0, 180)
    vols = []
    for _ in range(alea.randint(6, 9)):
        compagnie = alea.choice(_COMPAGNIES_DEMO)
        heure_depart = datetime.combine(jour, datetime.min.time()) + timedelta(
            hours=6 + alea.randint(0, 16), minutes=alea.choice([0, 15, 30, 45])
        )
        escales = 0 if alea.random() < 0.75 else 1
        duree = duree_base + alea.randint(-15, 25) + (escales * (60 + alea.randint(0, 90)))
        # Les low-cost affichent des prix d'appel plus bas.
        low_cost = compagnie in ("FR", "U2", "VY", "TO", "V7", "W6")
        prix = round((18 if low_cost else 55) + alea.random() * (90 if low_cost else 160), 2)
        vols.append(
            Vol(
                compagnie=compagnie,
                numero=f"{compagnie}{alea.randint(1000, 9999)}",
                origine=origine.upper(),
                destination=destination.upper(),
                depart=heure_depart,
                arrivee=heure_depart + timedelta(minutes=duree),
                escales=escales,
                prix_affiche=prix,
                source="demo",
            )
        )
    vols.sort(key=lambda v: v.depart)
    return vols


# --- Amadeus --------------------------------------------------------------

_AMADEUS_BASE = "https://test.api.amadeus.com"


def _jeton_amadeus() -> str:
    corps = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["AMADEUS_CLIENT_ID"],
            "client_secret": os.environ["AMADEUS_CLIENT_SECRET"],
        }
    ).encode()
    requete = urllib.request.Request(
        f"{_AMADEUS_BASE}/v1/security/oauth2/token",
        data=corps,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        return json.load(reponse)["access_token"]


def _rechercher_amadeus(
    origine: str, destination: str, jour: date, passagers: int
) -> list[Vol]:
    jeton = _jeton_amadeus()
    params = urllib.parse.urlencode(
        {
            "originLocationCode": origine.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": jour.isoformat(),
            "adults": passagers,
            "currencyCode": "EUR",
            "max": 20,
        }
    )
    requete = urllib.request.Request(
        f"{_AMADEUS_BASE}/v2/shopping/flight-offers?{params}",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        donnees = json.load(reponse)

    vols = []
    for offre in donnees.get("data", []):
        itineraire = offre["itineraries"][0]
        segments = itineraire["segments"]
        premier, dernier = segments[0], segments[-1]
        compagnie = (offre.get("validatingAirlineCodes") or [premier["carrierCode"]])[0]
        vols.append(
            Vol(
                compagnie=compagnie,
                numero=f"{premier['carrierCode']}{premier['number']}",
                origine=premier["departure"]["iataCode"],
                destination=dernier["arrival"]["iataCode"],
                depart=datetime.fromisoformat(premier["departure"]["at"]),
                arrivee=datetime.fromisoformat(dernier["arrival"]["at"]),
                escales=len(segments) - 1,
                # grandTotal couvre tous les passagers → ramené par passager.
                prix_affiche=round(float(offre["price"]["grandTotal"]) / passagers, 2),
                source="amadeus",
            )
        )
    return vols
