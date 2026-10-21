"""Tests hors ligne (sans Earth Engine) : python -m unittest discover tests"""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src import export
from src.config import Zone, build_jobs, load_config
from src.kml import read_polygon

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "config.yaml"


class TestKml(unittest.TestCase):
    def test_polygon_my_maps(self):
        ring = read_polygon(ROOT / "tests" / "data" / "zone_test.kml")
        self.assertEqual(len(ring), 5)
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(ring[0], [5.45, 43.21])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CONFIG)

    def test_jobs_count(self):
        jobs = build_jobs(self.cfg)
        n = len(self.cfg["zones"]) * len(self.cfg["years"]) * len(self.cfg["seasons"])
        self.assertEqual(len(jobs), n)

    def test_filters_and_names(self):
        jobs = build_jobs(self.cfg, zone="calanques", year=2024, season="ete")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].name, "calanques_2024_ete")
        self.assertEqual((jobs[0].start, jobs[0].end), ("2024-06-15", "2024-09-01"))

    def test_area(self):
        # 0,1° x 0,1° vers 45° de latitude : environ 7,9 km x 11,1 km.
        z = Zone("t", [[5.0, 45.0], [5.1, 45.0], [5.1, 45.1], [5.0, 45.1], [5.0, 45.0]])
        self.assertAlmostEqual(z.area_km2(), 87.0, delta=2.0)

    def test_dry_run(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = export.main(["--config", str(CONFIG), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("exports prévus", out.getvalue())


if __name__ == "__main__":
    unittest.main()
