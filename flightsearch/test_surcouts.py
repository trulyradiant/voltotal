"""Tests du moteur de surcoûts et de la recherche démo.

Lancer :  python -m pytest flightsearch/  (ou python -m unittest, sans dépendance)
"""
import unittest
from datetime import date

from flightsearch.surcouts import GrilleFrais, OptionsVoyage
from flightsearch.vols import _rechercher_demo


class TestSurcouts(unittest.TestCase):
    def setUp(self):
        self.grille = GrilleFrais()

    def test_ryanair_tout_paye(self):
        """Chez Ryanair, cabine + soute + siège + aéroport = 100 € par passager."""
        options = OptionsVoyage(passagers=1, bagage_cabine=True, bagages_soute=1,
                                choix_siege=True, enregistrement_aeroport=True)
        resultat = self.grille.calculer("FR", options)
        self.assertFalse(resultat.estimation)
        self.assertEqual(resultat.total, 12.0 + 25.0 + 8.0 + 55.0)

    def test_air_france_cabine_incluse(self):
        """Le bagage cabine est inclus chez Air France : pas de ligne de frais."""
        options = OptionsVoyage(passagers=1, bagage_cabine=True)
        resultat = self.grille.calculer("AF", options)
        self.assertEqual(resultat.total, 0.0)
        self.assertEqual(resultat.lignes, [])

    def test_multiplication_passagers_et_bagages(self):
        """2 passagers × 2 bagages soute Vueling (25 €) = 100 €."""
        options = OptionsVoyage(passagers=2, bagages_soute=2)
        resultat = self.grille.calculer("VY", options)
        self.assertEqual(resultat.total, 100.0)

    def test_compagnie_inconnue_estimation_prudente(self):
        options = OptionsVoyage(passagers=1, bagage_cabine=True, bagages_soute=1)
        resultat = self.grille.calculer("ZZ", options)
        self.assertTrue(resultat.estimation)
        self.assertEqual(resultat.total, 15.0 + 35.0)

    def test_sans_options_aucun_frais(self):
        resultat = self.grille.calculer("FR", OptionsVoyage(passagers=4))
        self.assertEqual(resultat.total, 0.0)


class TestRechercheDemo(unittest.TestCase):
    def test_deterministe(self):
        """Une même recherche renvoie toujours les mêmes vols (pas de loterie)."""
        a = _rechercher_demo("CDG", "BCN", date(2026, 9, 15))
        b = _rechercher_demo("CDG", "BCN", date(2026, 9, 15))
        self.assertEqual([(v.numero, v.prix_affiche) for v in a],
                         [(v.numero, v.prix_affiche) for v in b])

    def test_vols_plausibles(self):
        vols = _rechercher_demo("CDG", "BCN", date(2026, 9, 15))
        self.assertGreaterEqual(len(vols), 6)
        for vol in vols:
            self.assertGreater(vol.arrivee, vol.depart)
            self.assertGreater(vol.prix_affiche, 0)
            self.assertEqual(vol.origine, "CDG")
            self.assertEqual(vol.destination, "BCN")


if __name__ == "__main__":
    unittest.main()
