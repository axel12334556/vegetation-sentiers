"""Tests hors ligne du module d'analyses (sans connexion à Earth Engine)."""

import unittest

from src.analyses import VIS_BSI, VIS_EVOLUTION, VIS_NDVI, groupes_vers_tableau


class TestProfils(unittest.TestCase):
    def test_groupes_tries_et_centres(self):
        groupes = [
            {"classe": 2, "mean": 0.41, "count": 120},
            {"classe": 0, "mean": 0.35, "count": 80},
            {"classe": 1, "mean": 0.38, "count": 100},
        ]
        df = groupes_vers_tableau(groupes, pas=10)
        self.assertEqual(list(df["distance_m"]), [5.0, 15.0, 25.0])
        self.assertEqual(list(df["moyenne"]), [0.35, 0.38, 0.41])
        self.assertEqual(list(df["pixels"]), [80, 100, 120])

    def test_aucun_groupe(self):
        df = groupes_vers_tableau([], pas=10)
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), ["distance_m", "moyenne", "pixels"])


class TestPalettes(unittest.TestCase):
    def test_bornes(self):
        for vis in (VIS_NDVI, VIS_EVOLUTION, VIS_BSI):
            self.assertLess(vis["min"], vis["max"])
            self.assertGreaterEqual(len(vis["palette"]), 2)


if __name__ == "__main__":
    unittest.main()
