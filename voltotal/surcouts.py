"""Moteur de surcoûts : prix réel total d'un vol, options du voyageur comprises.

Deux sources de frais, dans cet ordre :

1. **Le tarif publié par la compagnie** pour cette offre précise, quand le
   fournisseur le connaît (franchise incluse, prix du bagage en soute).
   C'est la vérité : il est utilisé tel quel et marqué « compagnie ».
2. **La grille interne** (``data/frais_compagnies.json``), une estimation
   maintenue à la main, pour tout ce que l'API ne publie pas — le choix du
   siège et l'enregistrement à l'aéroport n'y sont jamais.

Un surcoût entièrement issu de la source 1 est signalé comme confirmé ;
sinon l'affichage annonce une estimation, pour ne pas promettre un prix
qu'on ne tient pas.
"""
from __future__ import annotations

import json
from pathlib import Path

from .modeles import LigneFrais, OptionsVoyage, Surcouts, Vol

_FICHIER_FRAIS = Path(__file__).parent / "data" / "frais_compagnies.json"


class GrilleFrais:
    def __init__(self, chemin: Path = _FICHIER_FRAIS):
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        self.compagnies: dict = donnees["compagnies"]
        self.defaut: dict = donnees["defaut"]
        self.derniere_mise_a_jour: str = donnees.get("_derniere_mise_a_jour", "?")

    def nom_compagnie(self, code: str) -> str:
        return self.compagnies.get(code.upper(), {}).get("nom", code.upper())

    def _prix_cabine(self, grille: dict) -> float:
        """Prix du bagage cabine lorsqu'il n'est pas compris.

        Si la grille l'affiche à 0 € parce qu'elle le supposait inclus, mais
        que l'offre de la compagnie dit le contraire, on retombe sur
        l'estimation prudente par défaut plutôt que de facturer 0 €.
        """
        prix = grille["bagage_cabine"]
        return prix if prix > 0 else self.defaut["bagage_cabine"]

    def tarifs(self, vol: Vol) -> dict:
        """Tarifs unitaires applicables à ce vol, avec l'origine de chaque prix.

        L'interface s'en sert pour recalculer le total instantanément quand le
        voyageur coche une option, sans rappeler le serveur : la *politique*
        (tarif compagnie ou estimation) est décidée ici, le navigateur ne fait
        que multiplier par le nombre de passagers et de bagages.
        """
        grille = self.compagnies.get(vol.compagnie.upper()) or self.defaut
        cabine_incluse = (
            vol.cabine_incluse if vol.cabine_incluse is not None else grille["cabine_incluse"]
        )
        if vol.prix_bagage_soute_annonce is not None:
            soute, source_soute = vol.prix_bagage_soute_annonce, "compagnie"
        else:
            soute, source_soute = grille["bagage_soute"], "grille"
        return {
            "bagage_cabine": {
                "prix": 0.0 if cabine_incluse else self._prix_cabine(grille),
                "inclus": bool(cabine_incluse),
                "source": "compagnie" if vol.cabine_incluse is not None else "grille",
            },
            "bagage_soute": {
                "prix": soute,
                "inclus": vol.bagages_soute_inclus or 0,
                "source": source_soute,
            },
            "choix_siege": {"prix": grille["choix_siege"], "source": "grille"},
            "enregistrement_aeroport": {
                "prix": grille["enregistrement_aeroport"],
                "source": "grille",
            },
        }

    def calculer(self, vol: Vol, options: OptionsVoyage) -> Surcouts:
        grille = self.compagnies.get(vol.compagnie.upper())
        resultat = Surcouts(estimation=grille is None)
        if grille is None:
            grille = self.defaut

        pax = options.passagers

        # --- Bagage cabine ---
        if options.bagage_cabine:
            # L'offre de la compagnie fait foi ; à défaut, la grille tranche.
            incluse = vol.cabine_incluse
            if incluse is None:
                incluse = grille["cabine_incluse"]
            if not incluse:
                resultat.lignes.append(
                    LigneFrais("Bagage cabine", round(self._prix_cabine(grille) * pax, 2), "grille")
                )

        # --- Bagages en soute : on ne paie que ceux hors franchise ---
        if options.bagages_soute > 0:
            inclus = vol.bagages_soute_inclus or 0
            a_payer = max(0, options.bagages_soute - inclus)
            if a_payer:
                if vol.prix_bagage_soute_annonce is not None:
                    prix_unite, source = vol.prix_bagage_soute_annonce, "compagnie"
                else:
                    prix_unite, source = grille["bagage_soute"], "grille"
                libelle = f"Bagage soute × {a_payer}" if a_payer > 1 else "Bagage soute"
                if inclus:
                    libelle += f" (dont {inclus} inclus)"
                resultat.lignes.append(
                    LigneFrais(libelle, round(prix_unite * a_payer * pax, 2), source)
                )

        # --- Options que les API ne publient pas : estimation seulement ---
        if options.choix_siege and grille["choix_siege"] > 0:
            resultat.lignes.append(
                LigneFrais("Choix du siège", round(grille["choix_siege"] * pax, 2), "grille")
            )
        if options.enregistrement_aeroport and grille["enregistrement_aeroport"] > 0:
            resultat.lignes.append(
                LigneFrais(
                    "Enregistrement à l'aéroport",
                    round(grille["enregistrement_aeroport"] * pax, 2),
                    "grille",
                )
            )

        return resultat
