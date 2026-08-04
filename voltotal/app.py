"""VolTotal — moteur de recherche de vols à prix tout compris.

Le serveur cherche les vols (Amadeus en temps réel, ou démonstration) et
renvoie, pour chaque vol, les tarifs unitaires des options avec leur origine.
L'interface recalcule alors le total à chaque changement sans rappeler le
serveur, ce qui garde l'affichage instantané sur téléphone.
"""
from __future__ import annotations

import difflib
import logging
import os
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

    @app.get("/sources")
    def sources():
        """Quelle source est active, et ce que ce processus voit réellement.

        Les *noms* des variables sont exposés, jamais leurs valeurs : c'est
        le seul moyen de distinguer une variable mal orthographiée, posée sur
        un autre service, ou simplement pas encore prise en compte faute de
        redéploiement — trois pannes indiscernables de l'extérieur.
        """
        attendues = ("DUFFEL_TOKEN", "DUFFEL_VERSION", "AMADEUS_CLIENT_ID",
                     "AMADEUS_CLIENT_SECRET", "AMADEUS_ENV", "FOURNISSEUR_VOLS")
        # Comparaison par ressemblance, et non par sous-chaîne : la faute la
        # plus fréquente (DUFFLE au lieu de DUFFEL) ne contient justement pas
        # le mot attendu.
        approchantes = sorted(
            nom for nom in os.environ
            if nom not in attendues
            and difflib.get_close_matches(nom.upper(), attendues, n=1, cutoff=0.75)
        )
        return jsonify(
            active=fournisseurs.source_active(),
            duffel_configure=fournisseurs.duffel.configure(),
            amadeus_configure=fournisseurs.amadeus.configure(),
            variables_reconnues=[nom for nom in attendues if os.environ.get(nom)],
            variables_non_reconnues=approchantes,
            version_deployee=(os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or None,
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
            nom_source=resultat.nom_source,
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
        source = fournisseurs.source_active()
        return jsonify(
            etat="ok",
            source=source,
            vols_temps_reel=source != "demo",
            grille_frais=grille.derniere_mise_a_jour,
        )

    return app
