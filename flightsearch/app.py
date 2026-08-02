"""VolTotal — moteur de recherche de vols à prix tout compris.

Chaque résultat affiche le prix d'appel de la compagnie ET le prix réel une
fois les options du voyageur ajoutées (bagages, siège, enregistrement),
pré-calculées via la grille de frais par compagnie. Tri par prix réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from flask import Flask, render_template, request

from .surcouts import GrilleFrais, OptionsVoyage, Surcouts
from .vols import Vol, rechercher


@dataclass
class Resultat:
    vol: Vol
    nom_compagnie: str
    surcouts: Surcouts
    prix_base_total: float  # prix affiché × passagers
    prix_reel_total: float  # prix base + surcoûts


def create_app() -> Flask:
    app = Flask(__name__)
    grille = GrilleFrais()

    @app.get("/")
    def accueil():
        demain = (date.today() + timedelta(days=1)).isoformat()
        return render_template("recherche.html", date_min=date.today().isoformat(),
                               date_defaut=demain)

    @app.get("/resultats")
    def resultats():
        origine = request.args.get("origine", "").strip().upper()
        destination = request.args.get("destination", "").strip().upper()
        erreurs = []
        if len(origine) != 3 or not origine.isalpha():
            erreurs.append("L'aéroport de départ doit être un code IATA à 3 lettres (ex. CDG).")
        if len(destination) != 3 or not destination.isalpha():
            erreurs.append("L'aéroport d'arrivée doit être un code IATA à 3 lettres (ex. BCN).")
        try:
            jour = date.fromisoformat(request.args.get("date", ""))
        except ValueError:
            jour = None
            erreurs.append("La date de départ est invalide.")

        options = OptionsVoyage(
            passagers=max(1, min(9, request.args.get("passagers", 1, type=int))),
            bagage_cabine=request.args.get("bagage_cabine") == "1",
            bagages_soute=max(0, min(3, request.args.get("bagages_soute", 0, type=int))),
            choix_siege=request.args.get("choix_siege") == "1",
            enregistrement_aeroport=request.args.get("enregistrement_aeroport") == "1",
        )

        if erreurs:
            return render_template("resultats.html", erreurs=erreurs, resultats=[],
                                   options=options, origine=origine,
                                   destination=destination, grille=grille), 400

        try:
            vols = rechercher(origine, destination, jour, options.passagers)
        except Exception:
            app.logger.exception("Echec de la recherche de vols")
            return render_template(
                "resultats.html",
                erreurs=["La recherche de vols a échoué, réessayez dans un instant."],
                resultats=[], options=options, origine=origine,
                destination=destination, grille=grille), 502

        liste = []
        for vol in vols:
            surcouts = grille.calculer(vol.compagnie, options)
            prix_base = round(vol.prix_affiche * options.passagers, 2)
            liste.append(
                Resultat(
                    vol=vol,
                    nom_compagnie=grille.nom_compagnie(vol.compagnie),
                    surcouts=surcouts,
                    prix_base_total=prix_base,
                    prix_reel_total=round(prix_base + surcouts.total, 2),
                )
            )
        liste.sort(key=lambda r: r.prix_reel_total)

        return render_template(
            "resultats.html", erreurs=[], resultats=liste, options=options,
            origine=origine, destination=destination, jour=jour, grille=grille)

    @app.template_filter("euros")
    def euros(montant: float) -> str:
        return f"{montant:,.2f} €".replace(",", " ").replace(".", ",")

    return app
