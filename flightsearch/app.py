"""VolTotal — moteur de recherche de vols à prix tout compris.

Le serveur cherche les vols (Amadeus en temps réel, ou démonstration) et
renvoie, pour chaque vol, les tarifs unitaires des options avec leur origine.
L'interface recalcule alors le total à chaque changement sans rappeler le
serveur, ce qui garde l'affichage instantané sur téléphone.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request

from . import fournisseurs
from .surcouts import GrilleFrais


def create_app() -> Flask:
    app = Flask(__name__)
    logging.basicConfig(level=logging.INFO)
    grille = GrilleFrais()

    @app.get("/")
    def accueil():
        return render_template(
            "index.html",
            aujourdhui=date.today().isoformat(),
            date_aller=(date.today() + timedelta(days=1)).isoformat(),
            date_retour=(date.today() + timedelta(days=8)).isoformat(),
            maj_grille=grille.derniere_mise_a_jour,
            recherche_aeroports=fournisseurs.amadeus.configure(),
        )

    @app.get("/api/vols")
    def api_vols():
        origine = (request.args.get("origine") or "").strip().upper()
        destination = (request.args.get("destination") or "").strip().upper()
        passagers = max(1, min(9, request.args.get("passagers", 1, type=int)))

        if not (origine.isalpha() and len(origine) == 3):
            return jsonify(erreur="Code aéroport de départ invalide."), 400
        if not (destination.isalpha() and len(destination) == 3):
            return jsonify(erreur="Code aéroport d'arrivée invalide."), 400
        if origine == destination:
            return jsonify(erreur="Le départ et l'arrivée doivent être différents."), 400
        try:
            jour = date.fromisoformat(request.args.get("date") or "")
        except ValueError:
            return jsonify(erreur="Date invalide."), 400

        try:
            resultat = fournisseurs.rechercher(origine, destination, jour, passagers)
        except Exception:  # le repli démonstration a déjà été tenté en amont
            app.logger.exception("Recherche de vols impossible")
            return jsonify(erreur="La recherche de vols a échoué, réessayez."), 502

        return jsonify(
            source=resultat.source,
            temps_reel=resultat.temps_reel,
            avertissement=resultat.avertissement,
            maj_grille=grille.derniere_mise_a_jour,
            vols=[
                {
                    "compagnie": vol.compagnie,
                    "nom": vol.nom_compagnie or grille.nom_compagnie(vol.compagnie),
                    "numero": vol.numero,
                    "depart": vol.depart.isoformat(),
                    "arrivee": vol.arrivee.isoformat(),
                    "duree_minutes": vol.duree_minutes,
                    "escales": vol.escales,
                    "prix_affiche": vol.prix_affiche,
                    "frais": grille.tarifs(vol),
                }
                for vol in resultat.vols
            ],
        )

    @app.get("/api/aeroports")
    def api_aeroports():
        mot_cle = (request.args.get("q") or "").strip()
        if len(mot_cle) < 2:
            return jsonify(aeroports=[])
        return jsonify(aeroports=fournisseurs.chercher_aeroports(mot_cle))

    @app.get("/sante")
    def sante():
        return jsonify(
            etat="ok",
            vols_temps_reel=fournisseurs.amadeus.configure(),
            grille_frais=grille.derniere_mise_a_jour,
        )

    return app
