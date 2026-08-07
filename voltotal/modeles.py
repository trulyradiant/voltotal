"""Objets partagés entre les fournisseurs de vols et le moteur de surcoûts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# Équipements sportifs facturés à la pièce, et non par passager.
EQUIPEMENTS = {
    "ski": "Skis / snowboard",
    "golf": "Clubs de golf",
    "velo": "Vélo",
    "surf": "Planche de surf",
}


@dataclass
class OptionsVoyage:
    """Qui voyage, et ce qu'il emporte vraiment.

    Les bagages et le siège se comptent par **passager payant** : un bébé sur
    les genoux n'a ni siège ni franchise bagage. Les équipements sportifs, eux,
    se comptent à la pièce — deux skieurs peuvent partager une housse.
    """

    adultes: int = 1
    enfants: list[int] = field(default_factory=list)  # âges, 2 à 11 ans
    bebes: int = 0  # moins de 2 ans, sur les genoux
    bagage_cabine: bool = False
    bagages_soute: int = 0
    choix_siege: bool = False
    enregistrement_aeroport: bool = False
    equipements: dict[str, int] = field(default_factory=dict)

    @property
    def passagers_payants(self) -> int:
        return self.adultes + len(self.enfants)

    @property
    def total_passagers(self) -> int:
        return self.adultes + len(self.enfants) + self.bebes

    def resume(self) -> str:
        parts = [f"{self.adultes} adulte" + ("s" if self.adultes > 1 else "")]
        if self.enfants:
            parts.append(f"{len(self.enfants)} enfant" + ("s" if len(self.enfants) > 1 else ""))
        if self.bebes:
            parts.append(f"{self.bebes} bébé" + ("s" if self.bebes > 1 else ""))
        return ", ".join(parts)


@dataclass
class Vol:
    """Un trajet proposé par un fournisseur.

    Les champs ``*_inclus`` et ``prix_*_annonce`` viennent de la compagnie
    quand le fournisseur les connaît : ils l'emportent alors sur la grille
    de frais interne, qui n'est qu'une estimation.
    """

    compagnie: str  # code IATA, ex. "AF"
    nom_compagnie: str
    numero: str
    origine: str
    destination: str
    depart: datetime
    arrivee: datetime
    escales: int
    prix_affiche: float  # prix d'appel, par passager
    source: str  # "amadeus" ou "demo"

    # Renseignés seulement si la compagnie les publie (via l'API).
    cabine_incluse: bool | None = None
    bagages_soute_inclus: int | None = None
    prix_bagage_soute_annonce: float | None = None  # par bagage, par passager
    reference: str | None = None  # identifiant de l'offre chez le fournisseur

    @property
    def duree_minutes(self) -> int:
        return int((self.arrivee - self.depart).total_seconds() // 60)

    @property
    def duree(self) -> str:
        return f"{self.duree_minutes // 60}h{self.duree_minutes % 60:02d}"


@dataclass
class LigneFrais:
    libelle: str
    total: float
    source: str  # "compagnie" (tarif publié) ou "grille" (estimation interne)


@dataclass
class Surcouts:
    lignes: list[LigneFrais] = field(default_factory=list)
    estimation: bool = False  # compagnie absente de la grille interne

    @property
    def total(self) -> float:
        return round(sum(ligne.total for ligne in self.lignes), 2)

    @property
    def confirme(self) -> bool:
        """Vrai si tous les frais viennent des tarifs publiés par la compagnie."""
        return bool(self.lignes) and all(l.source == "compagnie" for l in self.lignes)
