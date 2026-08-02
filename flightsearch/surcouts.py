"""Moteur de surcoûts : pré-calcule le prix réel total d'un vol.

Le prix affiché par les compagnies (surtout low-cost) exclut presque tout :
bagage cabine, soute, choix du siège, enregistrement à l'aéroport… Ce module
applique la grille de frais de chaque compagnie (data/frais_compagnies.json)
aux options du voyageur pour afficher un prix tout compris, sans surprise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_FICHIER_FRAIS = Path(__file__).parent / "data" / "frais_compagnies.json"


@dataclass
class OptionsVoyage:
    """Ce que le voyageur veut vraiment emporter/choisir, par passager."""

    passagers: int = 1
    bagage_cabine: bool = False
    bagages_soute: int = 0
    choix_siege: bool = False
    enregistrement_aeroport: bool = False


@dataclass
class LigneFrais:
    libelle: str
    montant_par_passager: float
    total: float


@dataclass
class Surcouts:
    lignes: list[LigneFrais] = field(default_factory=list)
    estimation: bool = False  # True si la compagnie est absente de la grille

    @property
    def total(self) -> float:
        return round(sum(ligne.total for ligne in self.lignes), 2)


class GrilleFrais:
    def __init__(self, chemin: Path = _FICHIER_FRAIS):
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        self.compagnies: dict = donnees["compagnies"]
        self.defaut: dict = donnees["defaut"]
        self.derniere_mise_a_jour: str = donnees.get("_derniere_mise_a_jour", "?")

    def nom_compagnie(self, code: str) -> str:
        return self.compagnies.get(code.upper(), {}).get("nom", code.upper())

    def calculer(self, code_compagnie: str, options: OptionsVoyage) -> Surcouts:
        """Applique la grille d'une compagnie aux options du voyageur.

        Les frais sont par passager et par trajet ; le total multiplie par le
        nombre de passagers (les bagages soute sont comptés par bagage).
        """
        grille = self.compagnies.get(code_compagnie.upper())
        resultat = Surcouts(estimation=grille is None)
        if grille is None:
            grille = self.defaut

        pax = options.passagers

        if options.bagage_cabine and not grille["cabine_incluse"]:
            prix = grille["bagage_cabine"]
            resultat.lignes.append(
                LigneFrais("Bagage cabine", prix, round(prix * pax, 2))
            )

        if options.bagages_soute > 0:
            prix = grille["bagage_soute"]
            nb = options.bagages_soute
            libelle = f"Bagage soute × {nb}" if nb > 1 else "Bagage soute"
            resultat.lignes.append(
                LigneFrais(libelle, round(prix * nb, 2), round(prix * nb * pax, 2))
            )

        if options.choix_siege and grille["choix_siege"] > 0:
            prix = grille["choix_siege"]
            resultat.lignes.append(
                LigneFrais("Choix du siège", prix, round(prix * pax, 2))
            )

        if options.enregistrement_aeroport and grille["enregistrement_aeroport"] > 0:
            prix = grille["enregistrement_aeroport"]
            resultat.lignes.append(
                LigneFrais("Enregistrement à l'aéroport", prix, round(prix * pax, 2))
            )

        return resultat
