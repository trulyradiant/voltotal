"""Connecteur Duffel : vols réels et prix des services annexes (bagages).

Duffel (https://duffel.com) distribue à la fois du contenu GDS, du NDC et
une partie des compagnies low-cost — celles qu'Amadeus ne couvre pas et qui
facturent le plus de suppléments. Son intérêt principal ici : l'appel
« available services » renvoie le **prix réel du bagage en soute** proposé
par la compagnie pour l'offre consultée.

Deux appels :

- ``POST /air/offer_requests?return_offers=true`` recherche de vols ;
- ``GET  /air/offers/{id}?return_available_services=true`` services annexes
  de l'offre, dont les bagages payants et leur tarif.

Attention : en mode test, Duffel répond avec une compagnie fictive
(« Duffel Airways »). Le contenu réel des compagnies demande un compte
validé par Duffel — voir le README.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from ..modeles import Vol

_LOG = logging.getLogger(__name__)

_BASE = "https://api.duffel.com"
_VERSION = os.environ.get("DUFFEL_VERSION", "v2")

# Nombre d'offres pour lesquelles on demande le tarif des bagages.
# Chaque appel est un aller-retour réseau : on le réserve aux moins chères.
_OFFRES_TARIFEES = int(os.environ.get("DUFFEL_OFFRES_TARIFEES", "8"))


class ErreurDuffel(RuntimeError):
    """L'API a répondu autre chose que ce qu'on attendait."""


def configure() -> bool:
    return bool(os.environ.get("DUFFEL_TOKEN"))


def _entetes() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['DUFFEL_TOKEN']}",
        "Duffel-Version": _VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _appeler(url: str, corps: bytes | None = None, methode: str = "GET") -> dict:
    requete = urllib.request.Request(url, data=corps, headers=_entetes(), method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=45) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode("utf-8", "replace")[:400]
        raise ErreurDuffel(f"HTTP {erreur.code} sur {url.split('?')[0]} : {detail}") from erreur
    except urllib.error.URLError as erreur:
        raise ErreurDuffel(f"Duffel injoignable : {erreur.reason}") from erreur


# --- Recherche de vols -----------------------------------------------------


def rechercher(origine: str, destination: str, jour: date, passagers: int) -> list[Vol]:
    corps = json.dumps(
        {
            "data": {
                "slices": [
                    {
                        "origin": origine.upper(),
                        "destination": destination.upper(),
                        "departure_date": jour.isoformat(),
                    }
                ],
                "passengers": [{"type": "adult"} for _ in range(max(1, passagers))],
                "cabin_class": "economy",
            }
        }
    ).encode()
    donnees = _appeler(
        f"{_BASE}/air/offer_requests?return_offers=true", corps=corps, methode="POST"
    )
    offres = ((donnees.get("data") or {}).get("offers")) or []

    vols = [_convertir(offre, passagers) for offre in offres]
    vols = [vol for vol in vols if vol is not None]
    vols.sort(key=lambda v: v.prix_affiche)

    _completer_tarifs_bagages(vols[:_OFFRES_TARIFEES])
    return vols


def _convertir(offre: dict, passagers: int) -> Vol | None:
    try:
        segments = offre["slices"][0]["segments"]
        premier, dernier = segments[0], segments[-1]
        proprietaire = offre.get("owner") or {}
        transporteur = premier.get("marketing_carrier") or proprietaire
        code = proprietaire.get("iata_code") or transporteur.get("iata_code") or "??"
        numero = premier.get("marketing_carrier_flight_number") or ""
        cabine, soute = _franchises(segments)
        return Vol(
            compagnie=code,
            nom_compagnie=proprietaire.get("name") or code,
            numero=f"{transporteur.get('iata_code', code)}{numero}",
            origine=premier["origin"]["iata_code"],
            destination=dernier["destination"]["iata_code"],
            depart=datetime.fromisoformat(premier["departing_at"]),
            arrivee=datetime.fromisoformat(dernier["arriving_at"]),
            escales=len(segments) - 1,
            # total_amount couvre tous les passagers → ramené par passager.
            prix_affiche=round(float(offre["total_amount"]) / max(1, passagers), 2),
            source="duffel",
            cabine_incluse=cabine,
            bagages_soute_inclus=soute,
            reference=offre.get("id"),
        )
    except (KeyError, IndexError, ValueError, TypeError) as erreur:
        _LOG.warning("Offre Duffel ignorée (format inattendu) : %s", erreur)
        return None


def _franchises(segments: list[dict]) -> tuple[bool | None, int | None]:
    """Franchises comprises dans le tarif, lues sur le premier segment.

    Duffel décrit les bagages inclus par passager et par segment. On retient
    le minimum sur le trajet : une franchise qui ne vaut que pour un segment
    n'est pas une franchise pour le voyageur.
    """
    cabine: bool | None = None
    soute: int | None = None
    for segment in segments:
        voyageurs = segment.get("passengers") or []
        if not voyageurs:
            continue
        bagages = voyageurs[0].get("baggages")
        if bagages is None:
            continue
        cabine_segment = False
        soute_segment = 0
        for bagage in bagages:
            quantite = int(bagage.get("quantity") or 0)
            if bagage.get("type") == "carry_on":
                cabine_segment = cabine_segment or quantite > 0
            elif bagage.get("type") == "checked":
                soute_segment += quantite
        cabine = cabine_segment if cabine is None else (cabine and cabine_segment)
        soute = soute_segment if soute is None else min(soute, soute_segment)
    return cabine, soute


# --- Prix réel des bagages (services annexes de l'offre) -------------------


def _completer_tarifs_bagages(vols: list[Vol]) -> None:
    """Renseigne ``prix_bagage_soute_annonce`` depuis les services de l'offre.

    Un échec est sans conséquence : le moteur retombe sur la grille interne
    et signale une estimation.
    """

    def traiter(vol: Vol) -> None:
        if not vol.reference:
            return
        try:
            prix = _prix_bagage(vol.reference)
        except ErreurDuffel as erreur:
            _LOG.info("Services annexes indisponibles pour %s : %s", vol.numero, erreur)
            return
        if prix is not None:
            vol.prix_bagage_soute_annonce = prix

    if vols:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(traiter, vols))


def chercher_aeroports(mot_cle: str, limite: int = 8) -> list[dict]:
    """« barcelone » → [{'code': 'BCN', 'nom': …, 'ville': …, 'pays': 'ES'}, …]

    Duffel renvoie des aéroports et des villes. Les deux sont utiles : un code
    de ville (PAR) couvre tous ses aéroports d'un coup, un code d'aéroport
    (CDG) cible précisément. Les villes sont donc listées en premier.
    """
    params = urllib.parse.urlencode({"name": mot_cle})
    donnees = _appeler(f"{_BASE}/places/suggestions?{params}")
    villes, aeroports = [], []
    for lieu in donnees.get("data") or []:
        code = lieu.get("iata_code")
        if not code:
            continue
        entree = {
            "code": code,
            "nom": lieu.get("name") or code,
            "ville": lieu.get("city_name") or (lieu.get("city") or {}).get("name") or "",
            "pays": lieu.get("iata_country_code") or "",
        }
        (villes if lieu.get("type") == "city" else aeroports).append(entree)
    return (villes + aeroports)[:limite]


def _prix_bagage(reference: str) -> float | None:
    """Prix du bagage en soute le moins cher proposé sur cette offre."""
    params = urllib.parse.urlencode({"return_available_services": "true"})
    donnees = _appeler(f"{_BASE}/air/offers/{urllib.parse.quote(reference)}?{params}")
    services = ((donnees.get("data") or {}).get("available_services")) or []
    candidats = []
    for service in services:
        if service.get("type") != "baggage":
            continue
        # On ne retient que la soute : le cabine payant est traité à part.
        if ((service.get("metadata") or {}).get("type") or "checked") != "checked":
            continue
        montant = service.get("total_amount")
        if montant is None:
            continue
        quantite = int(service.get("quantity") or 1) or 1
        candidats.append(round(float(montant) / quantite, 2))
    return min(candidats) if candidats else None
