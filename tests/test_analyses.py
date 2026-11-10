"""Tests hors ligne du module d'analyses (sans connexion à Earth Engine)."""

import unittest

from src.analyses import VIS_BSI, VIS_EVOLUTION, VIS_NDVI, VIS_RGB, distance_m, espacer, groupes_vers_tableau, milieu


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
        self.assertLess(VIS_RGB["min"], VIS_RGB["max"])
        self.assertEqual(len(VIS_RGB["bands"]), 3)


class TestPlans(unittest.TestCase):
    def test_milieu_ligne(self):
        geom = {"type": "LineString", "coordinates": [[5.0, 43.0], [5.1, 43.1], [5.2, 43.2]]}
        self.assertEqual(milieu(geom), (5.1, 43.1))

    def test_milieu_multiligne(self):
        geom = {"type": "MultiLineString", "coordinates": [[[5.0, 43.0], [5.1, 43.1]], [[5.2, 43.2], [5.3, 43.3]]]}
        self.assertIn(milieu(geom), [(5.2, 43.2), (5.1, 43.1)])

    def test_milieu_vide(self):
        self.assertIsNone(milieu(None))
        self.assertIsNone(milieu({"coordinates": []}))

    def test_distance(self):
        # 0,01 degré de latitude = environ 1113 m
        self.assertAlmostEqual(distance_m((5.0, 43.0), (5.0, 43.01)), 1113.2, delta=2)

    def test_espacer(self):
        points = [(5.0, 43.0), (5.0001, 43.0), (5.02, 43.0), (5.04, 43.0)]
        retenus = espacer(points, n=3, ecart_min=800)
        self.assertEqual(retenus, [(5.0, 43.0), (5.02, 43.0), (5.04, 43.0)])
        self.assertEqual(len(espacer(points, n=2, ecart_min=800)), 2)


if __name__ == "__main__":
    unittest.main()
