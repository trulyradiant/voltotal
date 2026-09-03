"""Connecteur Amadeus : vols réels et tarifs bagages publiés par les compagnies.

Trois appels sont utilisés (offre Self-Service, https://developers.amadeus.com) :

- ``/v1/security/oauth2/token``          jeton d'accès (mis en cache jusqu'à expiration) ;
- ``/v2/shopping/flight-offers``         recherche de vols ;
- ``/v1/shopping/flight-offers/pricing`` confirmation du prix **et**, avec
  ``include=bags``, le tarif réel des bagages de la compagnie pour cette offre.

C'est ce dernier appel qui transforme la grille interne en vrais prix : quand
la compagnie publie le tarif de son bagage en soute, on l'utilise tel quel.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from ..modeles import OptionsVoyage, Vol

_LOG = logging.getLogger(__name__)

# L'environnement de test est gratuit ; la production demande un dossier validé.
_BASE_TEST = "https://test.api.amadeus.com"
_BASE_PROD = "https://api.amadeus.com"

# Nombre d'offres pour lesquelles on va chercher le tarif bagages réel.
# Chaque tarification est un appel réseau : on le réserve aux moins chères.
_OFFRES_TARIFEES = int(os.environ.get("AMADEUS_OFFRES_TARIFEES", "8"))


class ErreurAmadeus(RuntimeError):
    """L'API a répondu autre chose que ce qu'on attendait."""


def configure() -> bool:
    return bool(os.environ.get("AMADEUS_CLIENT_ID") and os.environ.get("AMADEUS_CLIENT_SECRET"))


def _base() -> str:
    return _BASE_PROD if os.environ.get("AMADEUS_ENV", "test").lower() == "production" else _BASE_TEST


# --- Jeton d'accès, mis en cache entre les requêtes -------------------------

_jeton_verrou = threading.Lock()
_jeton_cache: dict[str, float | str] = {"valeur": "", "expire": 0.0}


def _jeton() -> str:
    with _jeton_verrou:
        if _jeton_cache["valeur"] and time.time() < float(_jeton_cache["expire"]):
            return str(_jeton_cache["valeur"])
        corps = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": os.environ["AMADEUS_CLIENT_ID"],
                "client_secret": os.environ["AMADEUS_CLIENT_SECRET"],
            }
        ).encode()
        donnees = _appeler(
            f"{_base()}/v1/security/oauth2/token",
            corps=corps,
            entetes={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _jeton_cache["valeur"] = donnees["access_token"]
        # On retire 60 s de marge pour ne jamais présenter un jeton expiré.
        _jeton_cache["expire"] = time.time() + float(donnees.get("expires_in", 1799)) - 60
        return str(_jeton_cache["valeur"])


def _appeler(url: str, corps: bytes | None = None, entetes: dict | None = None) -> dict:
    requete = urllib.request.Request(url, data=corps, headers=entetes or {})
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode("utf-8", "replace")[:400]
        raise ErreurAmadeus(f"HTTP {erreur.code} sur {url.split('?')[0]} : {detail}") from erreur
    except urllib.error.URLError as erreur:
        raise ErreurAmadeus(f"Amadeus injoignable : {erreur.reason}") from erreur


def _requete_json(chemin: str, params: dict) -> dict:
    url = f"{_base()}{chemin}?{urllib.parse.urlencode(params)}"
    return _appeler(url, entetes={"Authorization": f"Bearer {_jeton()}"})


# --- Recherche de vols -----------------------------------------------------


def rechercher(origine: str, destination: str, jour: date, options: OptionsVoyage,
               tarifs_bagages: bool = True) -> list[Vol]:
    parametres = {
        "originLocationCode": origine.upper(),
        "destinationLocationCode": destination.upper(),
        "departureDate": jour.isoformat(),
        "adults": max(1, options.adultes),
        "currencyCode": "EUR",
        "max": 20,
    }
    if options.enfants:
        parametres["children"] = len(options.enfants)
    if options.bebes:
        parametres["infants"] = options.bebes
    donnees = _requete_json("/v2/shopping/flight-offers", parametres)
    noms = (donnees.get("dictionaries") or {}).get("carriers") or {}
    offres = donnees.get("data") or []

    payants = max(1, options.passagers_payants)
    vols = [_convertir(offre, noms, payants) for offre in offres]
    vols = [vol for vol in vols if vol is not None]
    vols.sort(key=lambda v: v.prix_affiche)

    if tarifs_bagages:
        _completer_tarifs_bagages(vols[:_OFFRES_TARIFEES], offres, payants)
    return vols


def _convertir(offre: dict, noms: dict, passagers: int) -> Vol | None:
    try:
        segments = offre["itineraries"][0]["segments"]
        premier, dernier = segments[0], segments[-1]
        compagnie = (offre.get("validatingAirlineCodes") or [premier["carrierCode"]])[0]
        detail = _premier_fare_detail(offre)
        return Vol(
            compagnie=compagnie,
            nom_compagnie=(noms.get(compagnie) or compagnie).title(),
            numero=f"{premier['carrierCode']}{premier['number']}",
            origine=premier["departure"]["iataCode"],
            destination=dernier["arrival"]["iataCode"],
            depart=datetime.fromisoformat(premier["departure"]["at"]),
            arrivee=datetime.fromisoformat(dernier["arrival"]["at"]),
            escales=len(segments) - 1,
            # grandTotal couvre tous les passagers → ramené par passager.
            prix_affiche=round(float(offre["price"]["grandTotal"]) / max(1, passagers), 2),
            source="amadeus",
            cabine_incluse=_cabine_incluse(detail),
            bagages_soute_inclus=_soute_incluse(detail),
            reference=offre.get("id"),
        )
    except (KeyError, IndexError, ValueError, TypeError) as erreur:
        _LOG.warning("Offre Amadeus ignorée (format inattendu) : %s", erreur)
        return None


def _premier_fare_detail(offre: dict) -> dict:
    for tarif in offre.get("travelerPricings") or []:
        for detail in tarif.get("fareDetailsBySegment") or []:
            return detail
    return {}


def _cabine_incluse(detail: dict) -> bool | None:
    """Un bagage cabine est-il compris ? ``None`` si la compagnie ne le dit pas."""
    cabine = detail.get("includedCabinBags")
    if not isinstance(cabine, dict):
        return None
    if "quantity" in cabine:
        return int(cabine["quantity"]) > 0
    return bool(cabine.get("weight"))  # une franchise en kg vaut inclusion


def _soute_incluse(detail: dict) -> int | None:
    soute = detail.get("includedCheckedBags")
    if not isinstance(soute, dict):
        return None
    if "quantity" in soute:
        return int(soute["quantity"])
    # Une franchise exprimée en kilos vaut un bagage inclus.
    return 1 if soute.get("weight") else 0


# --- Tarif réel des bagages (appel de tarification) ------------------------


def _completer_tarifs_bagages(vols: list[Vol], offres: list[dict], passagers: int) -> None:
    """Renseigne ``prix_bagage_soute_annonce`` depuis les tarifs de la compagnie.

    Chaque offre demande un appel réseau : ils sont menés en parallèle et un
    échec est sans conséquence — on retombe simplement sur la grille interne.
    """
    par_reference = {offre.get("id"): offre for offre in offres}
    a_traiter = [vol for vol in vols if vol.reference in par_reference]
    if not a_traiter:
        return

    def traiter(vol: Vol) -> None:
        try:
            prix = _prix_bagage(par_reference[vol.reference], passagers)
        except ErreurAmadeus as erreur:
            _LOG.info("Tarif bagages indisponible pour %s : %s", vol.numero, erreur)
            return
        if prix is not None:
            vol.prix_bagage_soute_annonce = prix

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(traiter, a_traiter))


def _prix_bagage(offre: dict, passagers: int) -> float | None:
    """Prix d'un bagage en soute publié par la compagnie, par passager."""
    corps = json.dumps(
        {"data": {"type": "flight-offers-pricing", "flightOffers": [offre]}}
    ).encode()
    url = f"{_base()}/v1/shopping/flight-offers/pricing?{urllib.parse.urlencode({'include': 'bags'})}"
    donnees = _appeler(
        url,
        corps=corps,
        entetes={
            "Authorization": f"Bearer {_jeton()}",
            "Content-Type": "application/json",
        },
    )
    bagages = ((donnees.get("included") or {}).get("bags") or {}).values()
    candidats = []
    for bagage in bagages:
        if bagage.get("bagType") and bagage["bagType"].upper() != "CHECKED":
            continue
        montant = (bagage.get("price") or {}).get("amount")
        quantite = int(bagage.get("quantity") or 1) or 1
        if montant is None:
            continue
        # Le tarif porte sur `quantite` bagages, éventuellement pour plusieurs
        # voyageurs : on ramène au prix d'un bagage pour un passager.
        voyageurs = max(1, len(bagage.get("travelerIds") or [])) if bagage.get("travelerIds") else 1
        candidats.append(round(float(montant) / quantite / voyageurs, 2))
    return min(candidats) if candidats else None


# --- Recherche d'aéroport par nom de ville ---------------------------------


def chercher_aeroports(mot_cle: str, limite: int = 8) -> list[dict]:
    """« barcelone » → [{'code': 'BCN', 'nom': 'Barcelona', 'ville': ...}, ...]"""
    donnees = _requete_json(
        "/v1/reference-data/locations",
        {
            "subType": "AIRPORT,CITY",
            "keyword": mot_cle,
            "page[limit]": limite,
            "sort": "analytics.travelers.score",
            "view": "LIGHT",
        },
    )
    resultats = []
    for lieu in donnees.get("data") or []:
        code = lieu.get("iataCode")
        if not code:
            continue
        resultats.append(
            {
                "code": code,
                "nom": (lieu.get("name") or code).title(),
                "ville": (lieu.get("address") or {}).get("cityName", "").title(),
                "pays": (lieu.get("address") or {}).get("countryName", "").title(),
            }
        )
    return resultats
