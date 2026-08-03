"""Tests du moteur de surcoûts, des fournisseurs et de l'API.

Lancer :  python -m unittest discover flightsearch
Aucun appel réseau : les réponses Amadeus sont simulées.
"""
import json
import unittest
from datetime import date, datetime
from unittest import mock

from flightsearch.fournisseurs import amadeus, demo, duffel
from flightsearch.modeles import OptionsVoyage, Vol
from flightsearch.surcouts import GrilleFrais


def vol_simple(compagnie="FR", **extra):
    base = dict(
        compagnie=compagnie, nom_compagnie="Test", numero=f"{compagnie}1234",
        origine="CDG", destination="BCN",
        depart=datetime(2026, 9, 20, 10, 0), arrivee=datetime(2026, 9, 20, 12, 10),
        escales=0, prix_affiche=50.0, source="demo",
    )
    base.update(extra)
    return Vol(**base)


class TestGrilleInterne(unittest.TestCase):
    """Comportement quand la compagnie ne publie rien : on estime."""

    def setUp(self):
        self.grille = GrilleFrais()

    def test_ryanair_tout_paye(self):
        options = OptionsVoyage(passagers=1, bagage_cabine=True, bagages_soute=1,
                                choix_siege=True, enregistrement_aeroport=True)
        resultat = self.grille.calculer(vol_simple("FR"), options)
        self.assertEqual(resultat.total, 12.0 + 25.0 + 8.0 + 55.0)
        self.assertFalse(resultat.confirme)  # tout vient de la grille

    def test_air_france_cabine_incluse(self):
        resultat = self.grille.calculer(vol_simple("AF"), OptionsVoyage(bagage_cabine=True))
        self.assertEqual(resultat.total, 0.0)

    def test_multiplication_passagers_et_bagages(self):
        options = OptionsVoyage(passagers=2, bagages_soute=2)
        self.assertEqual(self.grille.calculer(vol_simple("VY"), options).total, 100.0)

    def test_compagnie_inconnue_estimation_prudente(self):
        options = OptionsVoyage(bagage_cabine=True, bagages_soute=1)
        resultat = self.grille.calculer(vol_simple("ZZ"), options)
        self.assertTrue(resultat.estimation)
        self.assertEqual(resultat.total, 15.0 + 35.0)

    def test_sans_options_aucun_frais(self):
        self.assertEqual(self.grille.calculer(vol_simple("FR"), OptionsVoyage(passagers=4)).total, 0.0)


class TestDonneesCompagnie(unittest.TestCase):
    """Quand la compagnie publie ses tarifs, ils l'emportent sur la grille."""

    def setUp(self):
        self.grille = GrilleFrais()

    def test_tarif_publie_prime_sur_la_grille(self):
        vol = vol_simple("FR", prix_bagage_soute_annonce=41.5)
        resultat = self.grille.calculer(vol, OptionsVoyage(bagages_soute=1))
        self.assertEqual(resultat.total, 41.5)  # et non les 25 € de la grille
        self.assertTrue(resultat.confirme)
        self.assertEqual(resultat.lignes[0].source, "compagnie")

    def test_franchise_incluse_non_facturee(self):
        vol = vol_simple("AF", bagages_soute_inclus=1, prix_bagage_soute_annonce=30.0)
        self.assertEqual(self.grille.calculer(vol, OptionsVoyage(bagages_soute=1)).total, 0.0)
        deux = self.grille.calculer(vol, OptionsVoyage(bagages_soute=2))
        self.assertEqual(deux.total, 30.0)
        self.assertIn("dont 1 inclus", deux.lignes[0].libelle)

    def test_cabine_payante_annoncee_contredit_la_grille(self):
        # La grille croit la cabine incluse chez AF ; l'offre dit le contraire.
        vol = vol_simple("AF", cabine_incluse=False)
        resultat = self.grille.calculer(vol, OptionsVoyage(bagage_cabine=True))
        self.assertGreater(resultat.total, 0.0)

    def test_tarifs_exposes_a_l_interface(self):
        vol = vol_simple("FR", prix_bagage_soute_annonce=41.5, bagages_soute_inclus=0)
        tarifs = self.grille.tarifs(vol)
        self.assertEqual(tarifs["bagage_soute"]["prix"], 41.5)
        self.assertEqual(tarifs["bagage_soute"]["source"], "compagnie")
        self.assertEqual(tarifs["choix_siege"]["source"], "grille")


OFFRE_AMADEUS = {
    "id": "1",
    "itineraries": [{"segments": [{
        "departure": {"iataCode": "CDG", "at": "2026-09-20T10:15:00"},
        "arrival": {"iataCode": "BCN", "at": "2026-09-20T12:25:00"},
        "carrierCode": "AF", "number": "1148",
    }]}],
    "price": {"currency": "EUR", "grandTotal": "240.00"},
    "validatingAirlineCodes": ["AF"],
    "travelerPricings": [{"fareDetailsBySegment": [{
        "cabin": "ECONOMY",
        "includedCheckedBags": {"quantity": 1},
        "includedCabinBags": {"quantity": 1},
    }]}],
}


class TestConnecteurAmadeus(unittest.TestCase):
    def test_decodage_offre_et_franchises(self):
        reponses = {
            "flight-offers": {"data": [OFFRE_AMADEUS],
                              "dictionaries": {"carriers": {"AF": "AIR FRANCE"}}},
            "pricing": {"included": {"bags": {"1": {
                "quantity": 1, "bagType": "CHECKED",
                "price": {"amount": "35.00", "currencyCode": "EUR"},
            }}}},
        }

        def faux_appel(url, corps=None, entetes=None):
            if "pricing" in url:
                return reponses["pricing"]
            return reponses["flight-offers"]

        with mock.patch.object(amadeus, "_appeler", side_effect=faux_appel), \
             mock.patch.object(amadeus, "_jeton", return_value="jeton"):
            vols = amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), 2)

        self.assertEqual(len(vols), 1)
        vol = vols[0]
        self.assertEqual(vol.compagnie, "AF")
        self.assertEqual(vol.nom_compagnie, "Air France")
        self.assertEqual(vol.prix_affiche, 120.0)  # 240 € pour 2 passagers
        self.assertEqual(vol.bagages_soute_inclus, 1)
        self.assertIs(vol.cabine_incluse, True)
        self.assertEqual(vol.prix_bagage_soute_annonce, 35.0)

    def test_offre_malformee_ignoree_sans_planter(self):
        reponse = {"data": [{"id": "x"}, OFFRE_AMADEUS], "dictionaries": {}}
        with mock.patch.object(amadeus, "_appeler", return_value=reponse), \
             mock.patch.object(amadeus, "_jeton", return_value="jeton"):
            vols = amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), 1)
        self.assertEqual(len(vols), 1)

    def test_erreur_http_convertie(self):
        with mock.patch.object(amadeus, "_jeton", return_value="jeton"), \
             mock.patch.object(amadeus, "_appeler", side_effect=amadeus.ErreurAmadeus("HTTP 401")):
            with self.assertRaises(amadeus.ErreurAmadeus):
                amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), 1)


OFFRE_DUFFEL = {
    "id": "off_123",
    "total_amount": "240.00",
    "total_currency": "EUR",
    "owner": {"iata_code": "FR", "name": "Ryanair"},
    "slices": [{"segments": [{
        "origin": {"iata_code": "CDG"}, "destination": {"iata_code": "BCN"},
        "departing_at": "2026-09-20T10:15:00", "arriving_at": "2026-09-20T12:25:00",
        "marketing_carrier": {"iata_code": "FR"}, "marketing_carrier_flight_number": "1148",
        "passengers": [{"baggages": [
            {"type": "carry_on", "quantity": 1},
            {"type": "checked", "quantity": 0},
        ]}],
    }]}],
}


class TestConnecteurDuffel(unittest.TestCase):
    def test_decodage_offre_et_services_annexes(self):
        def faux_appel(url, corps=None, methode="GET"):
            if "/air/offers/" in url:
                return {"data": {"available_services": [
                    {"type": "baggage", "total_amount": "45.00", "quantity": 1,
                     "metadata": {"type": "checked", "maximum_weight_kg": 20}},
                    {"type": "seat", "total_amount": "9.00"},
                ]}}
            return {"data": {"offers": [OFFRE_DUFFEL]}}

        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "duffel_test_x"}), \
             mock.patch.object(duffel, "_appeler", side_effect=faux_appel):
            vols = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), 2)

        self.assertEqual(len(vols), 1)
        vol = vols[0]
        self.assertEqual(vol.compagnie, "FR")
        self.assertEqual(vol.nom_compagnie, "Ryanair")
        self.assertEqual(vol.prix_affiche, 120.0)  # 240 € pour 2 passagers
        self.assertIs(vol.cabine_incluse, True)
        self.assertEqual(vol.bagages_soute_inclus, 0)
        self.assertEqual(vol.prix_bagage_soute_annonce, 45.0)  # et non les 25 € de la grille

    def test_franchise_retenue_est_la_plus_faible_du_trajet(self):
        # Une franchise soute sur un seul segment ne vaut pas pour le trajet.
        offre = json.loads(json.dumps(OFFRE_DUFFEL))
        segment = offre["slices"][0]["segments"][0]
        second = json.loads(json.dumps(segment))
        second["passengers"][0]["baggages"] = [
            {"type": "carry_on", "quantity": 0}, {"type": "checked", "quantity": 2},
        ]
        offre["slices"][0]["segments"].append(second)
        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "t"}), \
             mock.patch.object(duffel, "_appeler", return_value={"data": {"offers": [offre]}}):
            vol = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), 1)[0]
        self.assertIs(vol.cabine_incluse, False)
        self.assertEqual(vol.bagages_soute_inclus, 0)

    def test_offre_malformee_ignoree_sans_planter(self):
        reponse = {"data": {"offers": [{"id": "x"}, OFFRE_DUFFEL]}}
        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "t"}), \
             mock.patch.object(duffel, "_appeler", return_value=reponse):
            vols = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), 1)
        self.assertEqual(len(vols), 1)

    def test_prix_low_cost_confirme_par_la_compagnie(self):
        """Le cas qui manquait : un bagage Ryanair au tarif réel, pas estimé."""
        grille = GrilleFrais()
        vol = vol_simple("FR", prix_bagage_soute_annonce=45.0,
                         bagages_soute_inclus=0, cabine_incluse=True)
        resultat = grille.calculer(vol, OptionsVoyage(bagage_cabine=True, bagages_soute=1))
        self.assertEqual(resultat.total, 45.0)
        self.assertTrue(resultat.confirme)


class TestChoixDeLaSource(unittest.TestCase):
    def setUp(self):
        from flightsearch import fournisseurs
        self.fournisseurs = fournisseurs
        fournisseurs._cache.clear()

    def test_duffel_prefere_quand_les_deux_sont_configures(self):
        with mock.patch.dict("os.environ", {"FOURNISSEUR_VOLS": "auto"}), \
             mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(amadeus, "configure", return_value=True):
            self.assertEqual(self.fournisseurs.source_active(), "duffel")

    def test_source_imposee_par_la_configuration(self):
        with mock.patch.dict("os.environ", {"FOURNISSEUR_VOLS": "amadeus"}), \
             mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(amadeus, "configure", return_value=True):
            self.assertEqual(self.fournisseurs.source_active(), "amadeus")

    def test_sans_cles_on_bascule_en_demonstration(self):
        with mock.patch.object(duffel, "configure", return_value=False), \
             mock.patch.object(amadeus, "configure", return_value=False):
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 20), 1)
        self.assertFalse(resultat.temps_reel)
        self.assertTrue(resultat.vols)

    def test_panne_du_fournisseur_repli_avec_avertissement(self):
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(duffel, "rechercher", side_effect=duffel.ErreurDuffel("boum")):
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 21), 1)
        self.assertFalse(resultat.temps_reel)
        self.assertIn("temps réel", resultat.avertissement)
        self.assertTrue(resultat.vols)

    def test_liaison_sans_vol_repli_annonce(self):
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(duffel, "rechercher", return_value=[]):
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 22), 1)
        self.assertFalse(resultat.temps_reel)
        self.assertIn("Duffel", resultat.avertissement)


class TestDemonstration(unittest.TestCase):
    def test_deterministe(self):
        a = demo.rechercher("CDG", "BCN", date(2026, 9, 15), 1)
        b = demo.rechercher("CDG", "BCN", date(2026, 9, 15), 1)
        self.assertEqual([(v.numero, v.prix_affiche) for v in a],
                         [(v.numero, v.prix_affiche) for v in b])

    def test_vols_plausibles(self):
        for vol in demo.rechercher("CDG", "BCN", date(2026, 9, 15), 1):
            self.assertGreater(vol.arrivee, vol.depart)
            self.assertGreater(vol.prix_affiche, 0)


class TestApi(unittest.TestCase):
    def setUp(self):
        from flightsearch.app import create_app
        from flightsearch import fournisseurs
        fournisseurs._cache.clear()
        self.client = create_app().test_client()

    def test_page_accueil(self):
        reponse = self.client.get("/")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("VolTotal", reponse.get_data(as_text=True))

    def test_api_vols(self):
        reponse = self.client.get("/api/vols?origine=CDG&destination=BCN&date=2026-09-20&passagers=2")
        self.assertEqual(reponse.status_code, 200)
        donnees = json.loads(reponse.get_data(as_text=True))
        self.assertTrue(donnees["vols"])
        premier = donnees["vols"][0]
        for clef in ("compagnie", "nom", "numero", "depart", "arrivee", "prix_affiche", "frais"):
            self.assertIn(clef, premier)
        self.assertIn("bagage_soute", premier["frais"])

    def test_api_vols_saisie_invalide(self):
        for requete in ("origine=X&destination=BCN&date=2026-09-20",
                        "origine=CDG&destination=CDG&date=2026-09-20",
                        "origine=CDG&destination=BCN&date=pasunedate"):
            reponse = self.client.get("/api/vols?" + requete)
            self.assertEqual(reponse.status_code, 400, requete)
            self.assertIn("erreur", json.loads(reponse.get_data(as_text=True)))

    def test_sante(self):
        donnees = json.loads(self.client.get("/sante").get_data(as_text=True))
        self.assertEqual(donnees["etat"], "ok")


if __name__ == "__main__":
    unittest.main()
