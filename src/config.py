"""Chargement de la configuration et construction de la liste des exports à lancer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from .kml import read_polygon


@dataclass
class Zone:
    name: str
    ring: list[list[float]]  # [[lon, lat], ...], anneau fermé

    def area_km2(self) -> float:
        """Surface approximative (projection équirectangulaire locale)."""
        lat0 = sum(p[1] for p in self.ring) / len(self.ring)
        kx = 111.32 * math.cos(math.radians(lat0))
        ky = 110.57
        pts = [(lon * kx, lat * ky) for lon, lat in self.ring]
        s = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            s += x1 * y2 - x2 * y1
        return abs(s) / 2


@dataclass
class ExportJob:
    zone: Zone
    year: int
    season: str
    start: str  # AAAA-MM-JJ inclus
    end: str  # AAAA-MM-JJ exclu

    @property
    def name(self) -> str:
        return f"{self.zone.name}_{self.year}_{self.season}"


def _bbox_ring(bbox: list[float]) -> list[list[float]]:
    west, south, east, north = bbox
    if not (west < east and south < north):
        raise ValueError(f"bbox invalide (attendu [ouest, sud, est, nord]) : {bbox}")
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def load_config(path: str | Path) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_base_dir"] = path.parent.parent  # racine du dépôt (config/ est un sous-dossier)
    return cfg


def load_zones(cfg: dict) -> list[Zone]:
    zones = []
    for name, spec in cfg["zones"].items():
        if "kml" in spec:
            ring = read_polygon(cfg["_base_dir"] / spec["kml"])
        elif "bbox" in spec:
            ring = _bbox_ring(spec["bbox"])
        else:
            raise ValueError(f"La zone '{name}' doit avoir 'kml' ou 'bbox'.")
        zones.append(Zone(name=name, ring=ring))
    return zones


def build_jobs(cfg: dict, zone: str | None = None, year: int | None = None,
               season: str | None = None) -> list[ExportJob]:
    jobs = []
    for z in load_zones(cfg):
        if zone and z.name != zone:
            continue
        for y in cfg["years"]:
            if year and y != year:
                continue
            for s_name, s in cfg["seasons"].items():
                if season and s_name != season:
                    continue
                start = f"{y}-{s['start']}"
                end_year = y + 1 if s["end"] < s["start"] else y
                end = f"{end_year}-{s['end']}"
                jobs.append(ExportJob(zone=z, year=y, season=s_name, start=start, end=end))
    return jobs


def estimate_mb(job: ExportJob, cfg: dict) -> float:
    """Taille approximative d'un export (float32, non compressé)."""
    scale = cfg["export"]["scale"]
    pixels = job.zone.area_km2() * 1e6 / (scale * scale)
    return pixels * 4 * len(cfg["export"]["bands"]) / 1e6
