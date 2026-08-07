"""Tests du moteur de surcoûts, des fournisseurs et de l'API.

Lancer :  python -m unittest discover voltotal
Aucun appel réseau : les réponses Amadeus sont simulées.
"""
import json
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from voltotal.fournisseurs import amadeus, demo, duffel
from voltotal.modeles import EQUIPEMENTS, OptionsVoyage, Vol
from voltotal.surcouts import GrilleFrais


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
        options = OptionsVoyage(adultes=1, bagage_cabine=True, bagages_soute=1,
                                choix_siege=True, enregistrement_aeroport=True)
        resultat = self.grille.calculer(vol_simple("FR"), options)
        self.assertEqual(resultat.total, 12.0 + 25.0 + 8.0 + 55.0)
        self.assertFalse(resultat.confirme)  # tout vient de la grille

    def test_air_france_cabine_incluse(self):
        resultat = self.grille.calculer(vol_simple("AF"), OptionsVoyage(bagage_cabine=True))
        self.assertEqual(resultat.total, 0.0)

    def test_multiplication_passagers_et_bagages(self):
        options = OptionsVoyage(adultes=2, bagages_soute=2)
        self.assertEqual(self.grille.calculer(vol_simple("VY"), options).total, 100.0)

    def test_compagnie_inconnue_estimation_prudente(self):
        options = OptionsVoyage(bagage_cabine=True, bagages_soute=1)
        resultat = self.grille.calculer(vol_simple("ZZ"), options)
        self.assertTrue(resultat.estimation)
        self.assertEqual(resultat.total, 15.0 + 35.0)

    def test_sans_options_aucun_frais(self):
        self.assertEqual(self.grille.calculer(vol_simple("FR"), OptionsVoyage(adultes=4)).total, 0.0)


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
            vols = amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage(adultes=2))

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
            vols = amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage())
        self.assertEqual(len(vols), 1)

    def test_erreur_http_convertie(self):
        with mock.patch.object(amadeus, "_jeton", return_value="jeton"), \
             mock.patch.object(amadeus, "_appeler", side_effect=amadeus.ErreurAmadeus("HTTP 401")):
            with self.assertRaises(amadeus.ErreurAmadeus):
                amadeus.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage())


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
            vols = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage(adultes=2))

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
            vol = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage())[0]
        self.assertIs(vol.cabine_incluse, False)
        self.assertEqual(vol.bagages_soute_inclus, 0)

    def test_offre_malformee_ignoree_sans_planter(self):
        reponse = {"data": {"offers": [{"id": "x"}, OFFRE_DUFFEL]}}
        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "t"}), \
             mock.patch.object(duffel, "_appeler", return_value=reponse):
            vols = duffel.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage())
        self.assertEqual(len(vols), 1)

    def test_prix_low_cost_confirme_par_la_compagnie(self):
        """Le cas qui manquait : un bagage Ryanair au tarif réel, pas estimé."""
        grille = GrilleFrais()
        vol = vol_simple("FR", prix_bagage_soute_annonce=45.0,
                         bagages_soute_inclus=0, cabine_incluse=True)
        resultat = grille.calculer(vol, OptionsVoyage(bagage_cabine=True, bagages_soute=1))
        self.assertEqual(resultat.total, 45.0)
        self.assertTrue(resultat.confirme)


class TestRechercheAeroports(unittest.TestCase):
    """L'autocomplétion doit marcher avec le seul jeton Duffel."""

    REPONSE = {"data": [
        {"type": "city", "iata_code": "LON", "name": "London",
         "iata_country_code": "GB", "airports": [
             {"iata_code": "LHR", "name": "Heathrow"},
             {"iata_code": "LGW", "name": "Gatwick"}]},
        {"type": "airport", "iata_code": "LHR", "name": "Heathrow",
         "city_name": "London", "iata_country_code": "GB"},   # déjà couvert
        {"type": "airport", "iata_code": "LTN", "name": "Luton",
         "city_name": "London", "iata_country_code": "GB"},   # à ajouter
        {"type": "airport", "name": "Sans code IATA"},        # ignoré
    ]}

    def _chercher(self):
        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "t"}), \
             mock.patch.object(duffel, "_appeler", return_value=self.REPONSE):
            return duffel.chercher_aeroports("london")

    def test_ville_groupee_avec_ses_aeroports(self):
        resultats = self._chercher()
        ville = resultats[0]
        self.assertEqual(ville["ville"], "London")
        self.assertEqual(ville["code_tous"], "LON")  # plusieurs aéroports
        self.assertEqual([a["code"] for a in ville["aeroports"]], ["LHR", "LGW"])

    def test_aeroport_deja_couvert_non_duplique(self):
        codes = [a["code"] for lieu in self._chercher() for a in lieu["aeroports"]]
        self.assertEqual(codes.count("LHR"), 1)

    def test_aeroport_isole_ajoute_et_entree_sans_code_ignoree(self):
        resultats = self._chercher()
        self.assertEqual(len(resultats), 2)  # la ville + Luton
        self.assertEqual(resultats[1]["aeroports"][0]["code"], "LTN")
        self.assertIsNone(resultats[1]["code_tous"])

    def test_ville_a_un_seul_aeroport_sans_choix_global(self):
        reponse = {"data": [{"type": "city", "iata_code": "NCE", "name": "Nice",
                             "iata_country_code": "FR",
                             "airports": [{"iata_code": "NCE", "nom": "Nice"}]}]}
        with mock.patch.dict("os.environ", {"DUFFEL_TOKEN": "t"}), \
             mock.patch.object(duffel, "_appeler", return_value=reponse):
            self.assertIsNone(duffel.chercher_aeroports("nice")[0]["code_tous"])

    def test_duffel_utilise_sans_amadeus(self):
        from voltotal import fournisseurs
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(amadeus, "configure", return_value=False), \
             mock.patch.object(duffel, "_appeler", return_value=self.REPONSE):
            self.assertTrue(fournisseurs.recherche_aeroports_disponible())
            self.assertTrue(fournisseurs.chercher_aeroports("london"))

    def test_repli_sur_amadeus_si_duffel_echoue(self):
        from voltotal import fournisseurs
        attendu = [{"ville": "Londres", "pays": "GB", "code_tous": None,
                    "aeroports": [{"code": "LHR", "nom": "Heathrow"}]}]
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(duffel, "chercher_aeroports", side_effect=duffel.ErreurDuffel("boum")), \
             mock.patch.object(amadeus, "configure", return_value=True), \
             mock.patch.object(amadeus, "chercher_aeroports", return_value=attendu):
            self.assertEqual(fournisseurs.chercher_aeroports("londres"), attendu)

    def test_aucune_source_ne_plante_pas(self):
        from voltotal import fournisseurs
        with mock.patch.object(duffel, "configure", return_value=False), \
             mock.patch.object(amadeus, "configure", return_value=False):
            self.assertFalse(fournisseurs.recherche_aeroports_disponible())
            self.assertEqual(fournisseurs.chercher_aeroports("londres"), [])


class TestChoixDeLaSource(unittest.TestCase):
    def setUp(self):
        from voltotal import fournisseurs
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
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 20), OptionsVoyage())
        self.assertFalse(resultat.temps_reel)
        self.assertTrue(resultat.vols)

    def test_panne_du_fournisseur_repli_avec_avertissement(self):
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(duffel, "rechercher", side_effect=duffel.ErreurDuffel("boum")):
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 21), OptionsVoyage())
        self.assertFalse(resultat.temps_reel)
        self.assertIn("temps réel", resultat.avertissement)
        self.assertTrue(resultat.vols)

    def test_liaison_sans_vol_repli_annonce(self):
        with mock.patch.object(duffel, "configure", return_value=True), \
             mock.patch.object(duffel, "rechercher", return_value=[]):
            resultat = self.fournisseurs.rechercher("CDG", "BCN", date(2026, 9, 22), OptionsVoyage())
        self.assertFalse(resultat.temps_reel)
        self.assertIn("Duffel", resultat.avertissement)


class TestDemonstration(unittest.TestCase):
    def test_deterministe(self):
        a = demo.rechercher("CDG", "BCN", date(2026, 9, 15), OptionsVoyage())
        b = demo.rechercher("CDG", "BCN", date(2026, 9, 15), OptionsVoyage())
        self.assertEqual([(v.numero, v.prix_affiche) for v in a],
                         [(v.numero, v.prix_affiche) for v in b])

    def test_vols_plausibles(self):
        for vol in demo.rechercher("CDG", "BCN", date(2026, 9, 15), OptionsVoyage()):
            self.assertGreater(vol.arrivee, vol.depart)
            self.assertGreater(vol.prix_affiche, 0)


class TestApi(unittest.TestCase):
    def setUp(self):
        from voltotal.app import create_app
        from voltotal import fournisseurs
        fournisseurs._cache.clear()
        self.client = create_app().test_client()

    def test_page_accueil(self):
        reponse = self.client.get("/")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("VolTotal", reponse.get_data(as_text=True))

    def test_api_vols(self):
        reponse = self.client.get("/api/vols?origine=CDG&destination=BCN&date=2026-09-20&adultes=2")
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


class TestBaseLieux(unittest.TestCase):
    """Saisie par nom de ville, sans aucune API."""

    def setUp(self):
        from voltotal.lieux import BaseLieux
        self.base = BaseLieux()

    def test_ville_entiere(self):
        resultats = self.base.rechercher("paris")
        self.assertEqual(resultats[0]["ville"], "Paris")
        self.assertEqual(resultats[0]["code_tous"], "PAR")
        self.assertEqual([a["code"] for a in resultats[0]["aeroports"]], ["CDG", "ORY", "BVA"])

    def test_debut_de_nom_et_accents_ignores(self):
        self.assertEqual(self.base.rechercher("lond")[0]["ville"], "Londres")
        self.assertEqual(self.base.rechercher("geneve")[0]["ville"], "Genève")
        self.assertEqual(self.base.rechercher("Genève")[0]["ville"], "Genève")

    def test_recherche_par_code_ou_nom_d_aeroport(self):
        self.assertEqual(self.base.rechercher("cdg")[0]["ville"], "Paris")
        self.assertEqual(self.base.rechercher("gatwick")[0]["ville"], "Londres")

    def test_ville_sans_code_global(self):
        """Barcelone n'a pas de code IATA de ville : pas de « tous les aéroports »."""
        barcelone = self.base.rechercher("barcelone")[0]
        self.assertIsNone(barcelone["code_tous"])
        self.assertEqual(len(barcelone["aeroports"]), 3)

    def test_ville_prioritaire_sur_correspondance_interne(self):
        # « nice » apparaît aussi dans d'autres champs : la ville passe devant.
        self.assertEqual(self.base.rechercher("nice")[0]["ville"], "Nice")

    def test_saisie_vide_ou_inconnue(self):
        self.assertEqual(self.base.rechercher(""), [])
        self.assertEqual(self.base.rechercher("zzzzz"), [])


class TestFusionLieux(unittest.TestCase):
    def test_l_api_complete_sans_doublon(self):
        from voltotal import lieux
        locaux = [{"ville": "Paris", "pays": "France", "code_tous": "PAR",
                   "aeroports": [{"code": "CDG", "nom": "Roissy"}]}]
        distants = [
            {"ville": "paris", "pays": "FR", "code_tous": None,
             "aeroports": [{"code": "CDG", "nom": "Charles de Gaulle"}]},  # doublon
            {"ville": "Parme", "pays": "IT", "code_tous": None,
             "aeroports": [{"code": "PMF", "nom": "Parme"}]},
        ]
        fusion = lieux.fusionner(locaux, distants)
        self.assertEqual([v["ville"] for v in fusion], ["Paris", "Parme"])

    def test_meme_aeroport_sous_un_autre_nom_de_ville(self):
        from voltotal import lieux
        locaux = [{"ville": "Nice", "pays": "France", "code_tous": None,
                   "aeroports": [{"code": "NCE", "nom": "Côte d'Azur"}]}]
        distants = [{"ville": "Nizza", "pays": "IT", "code_tous": None,
                     "aeroports": [{"code": "NCE", "nom": "Nice"}]}]
        self.assertEqual(len(lieux.fusionner(locaux, distants)), 1)


class TestVoyageurs(unittest.TestCase):
    """Adultes, enfants et bébés ne comptent pas de la même façon."""

    def setUp(self):
        self.grille = GrilleFrais()

    def test_bebe_ne_paie_ni_siege_ni_bagage(self):
        """Un bébé sur les genoux n'ajoute aucun supplément."""
        sans = OptionsVoyage(adultes=2, bagages_soute=1, choix_siege=True)
        avec = OptionsVoyage(adultes=2, bebes=1, bagages_soute=1, choix_siege=True)
        self.assertEqual(self.grille.calculer(vol_simple("FR"), sans).total,
                         self.grille.calculer(vol_simple("FR"), avec).total)
        self.assertEqual(avec.total_passagers, 3)
        self.assertEqual(avec.passagers_payants, 2)

    def test_enfant_compte_comme_un_passager_payant(self):
        options = OptionsVoyage(adultes=2, enfants=[4, 9], bagages_soute=1)
        # 4 passagers payants × 25 € de soute chez Vueling
        self.assertEqual(self.grille.calculer(vol_simple("VY"), options).total, 100.0)

    def test_resume_lisible(self):
        self.assertEqual(OptionsVoyage(adultes=1).resume(), "1 adulte")
        self.assertEqual(OptionsVoyage(adultes=2, enfants=[5], bebes=1).resume(),
                         "2 adultes, 1 enfant, 1 bébé")

    def test_duffel_transmet_ages_et_bebes(self):
        options = OptionsVoyage(adultes=2, enfants=[4, 9], bebes=1)
        self.assertEqual(
            duffel._voyageurs(options),
            [{"type": "adult"}, {"type": "adult"}, {"age": 4}, {"age": 9},
             {"type": "infant_without_seat"}],
        )


class TestEquipementSportif(unittest.TestCase):
    """Les équipements se facturent à la pièce, pas par passager."""

    def setUp(self):
        self.grille = GrilleFrais()

    def test_prix_independant_du_nombre_de_passagers(self):
        seul = OptionsVoyage(adultes=1, equipements={"ski": 1})
        famille = OptionsVoyage(adultes=4, equipements={"ski": 1})
        self.assertEqual(self.grille.calculer(vol_simple("FR"), seul).total, 60.0)
        self.assertEqual(self.grille.calculer(vol_simple("FR"), famille).total, 60.0)

    def test_plusieurs_pieces(self):
        options = OptionsVoyage(equipements={"ski": 2})
        resultat = self.grille.calculer(vol_simple("FR"), options)
        self.assertEqual(resultat.total, 120.0)
        self.assertIn("× 2", resultat.lignes[0].libelle)

    def test_velo_a_son_propre_tarif(self):
        velo = self.grille.calculer(vol_simple("VY"), OptionsVoyage(equipements={"velo": 1}))
        ski = self.grille.calculer(vol_simple("VY"), OptionsVoyage(equipements={"ski": 1}))
        self.assertEqual(velo.total, 60.0)
        self.assertEqual(ski.total, 50.0)

    def test_equipement_inconnu_ignore(self):
        options = OptionsVoyage(equipements={"trottinette": 3})
        self.assertEqual(self.grille.calculer(vol_simple("FR"), options).total, 0.0)

    def test_tous_les_equipements_ont_un_tarif(self):
        for cle in EQUIPEMENTS:
            options = OptionsVoyage(equipements={cle: 1})
            self.assertGreater(self.grille.calculer(vol_simple("FR"), options).total, 0.0, cle)


class TestCalendrier(unittest.TestCase):
    def setUp(self):
        from voltotal.app import create_app
        from voltotal import fournisseurs
        fournisseurs._cache.clear()
        self.client = create_app().test_client()

    def test_fenetre_autour_de_la_date(self):
        futur = (date.today() + timedelta(days=30)).isoformat()
        donnees = json.loads(self.client.get(
            f"/api/calendrier?origine=CDG&destination=BCN&date={futur}").get_data(as_text=True))
        self.assertEqual(len(donnees["jours"]), 7)  # ±3 jours par défaut
        for jour in donnees["jours"]:
            self.assertIn("prix", jour)
            self.assertIn("frais", jour)

    def test_jours_passes_ecartes(self):
        """Chiffrer un vol déjà parti n'a aucun intérêt."""
        donnees = json.loads(self.client.get(
            f"/api/calendrier?origine=CDG&destination=BCN&date={date.today().isoformat()}"
        ).get_data(as_text=True))
        self.assertEqual(len(donnees["jours"]), 4)  # aujourd'hui + 3 jours
        self.assertEqual(donnees["jours"][0]["date"], date.today().isoformat())

    def test_saisie_invalide(self):
        for requete in ("origine=X&destination=BCN&date=2026-09-20",
                        "origine=CDG&destination=BCN&date=pasunedate"):
            self.assertEqual(self.client.get("/api/calendrier?" + requete).status_code, 400)
