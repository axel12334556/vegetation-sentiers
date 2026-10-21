"""Lecture des polygones exportés depuis Google My Maps (.kml ou .kmz)."""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

KML_NS = "{http://www.opengis.net/kml/2.2}"


def _read_kml_text(path: Path) -> bytes:
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            kml_names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError(f"Aucun fichier .kml dans {path}")
            return archive.read(kml_names[0])
    return path.read_bytes()


def _parse_coordinates(text: str) -> list[list[float]]:
    points = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        points.append([lon, lat])
    return points


def read_polygon(path: str | Path) -> list[list[float]]:
    """Renvoie l'anneau extérieur du premier polygone du fichier, en [[lon, lat], ...].

    Une ligne fermée dessinée dans My Maps est acceptée comme contour.
    """
    path = Path(path)
    root = ET.fromstring(_read_kml_text(path))

    for tag in ("Polygon", "LineString"):
        for element in root.iter(f"{KML_NS}{tag}"):
            coords = element.find(f".//{KML_NS}coordinates")
            if coords is None or not coords.text:
                continue
            points = _parse_coordinates(coords.text)
            if len(points) < 3:
                continue
            if points[0] != points[-1]:
                points.append(points[0])
            return points

    raise ValueError(f"Aucun polygone exploitable dans {path}")
