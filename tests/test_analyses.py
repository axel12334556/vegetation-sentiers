"""Tests hors ligne du module d'analyses (sans connexion à Earth Engine)."""

import unittest

import pandas as pd

from src.analyses import VIS_BSI, VIS_EVOLUTION, VIS_NDVI, VIS_RGB, distance_m, espacer, groupes_vers_tableau, milieu, resumer_troncons, tableau_occupation


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


def _troncons(proche, temoin, pixels=20):
    return pd.DataFrame({"proche": proche, "temoin": temoin,
                         "pixels_proche": [pixels] * len(proche), "pixels_temoin": [pixels] * len(proche)})


class TestRobustesse(unittest.TestCase):
    def test_ecart_constant_distingue_de_zero(self):
        # tous les tronçons sont 0,01 sous leur témoin : l'intervalle exclut 0
        r = resumer_troncons(_troncons([0.50, 0.60, 0.40, 0.55], [0.51, 0.61, 0.41, 0.56]), n_boot=500)
        self.assertAlmostEqual(r["ecart_moyen"], -0.01)
        self.assertTrue(r["distingue_de_zero"])
        self.assertEqual(r["part_troncons_sous_temoin"], 1.0)

    def test_ecarts_de_signes_opposes_pas_distingues(self):
        r = resumer_troncons(_troncons([0.52, 0.48, 0.52, 0.48, 0.52, 0.48], [0.50] * 6), n_boot=500)
        self.assertAlmostEqual(r["ecart_moyen"], 0.0)
        self.assertFalse(r["distingue_de_zero"])
        self.assertEqual(r["part_troncons_sous_temoin"], 0.5)

    def test_filtre_pixels_et_valeurs_manquantes(self):
        df = _troncons([0.5, None, 0.5, 0.5], [0.4, 0.4, 0.4, 0.4])
        df.loc[2, "pixels_proche"] = 1          # trop peu de pixels
        r = resumer_troncons(df, pixels_min=3, n_boot=100)
        self.assertEqual(r["n_troncons"], 2)

    def test_trop_peu_de_troncons(self):
        r = resumer_troncons(_troncons([0.5], [0.4]))
        self.assertIsNone(r["ecart_moyen"])


class TestOccupation(unittest.TestCase):
    def test_parts_par_classe(self):
        df = tableau_occupation({"z1": {"10": 75, "40": 25}, "z2": {"10.0": 50, "50": 50}})
        self.assertAlmostEqual(df.loc["z1", "forêt"], 0.75)
        self.assertAlmostEqual(df.loc["z1", "cultures"], 0.25)
        self.assertAlmostEqual(df.loc["z1", "bâti"], 0.0)
        self.assertAlmostEqual(df.loc["z2", "bâti"], 0.5)
        self.assertEqual(list(df.columns), ["forêt", "cultures", "bâti"])


if __name__ == "__main__":
    unittest.main()
