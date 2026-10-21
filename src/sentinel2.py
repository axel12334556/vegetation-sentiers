"""Composites Sentinel-2 et indices spectraux, calculés côté Google Earth Engine."""

from __future__ import annotations

import ee

COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# Classes SCL (Scene Classification) écartées : saturé, ombre de nuage, nuages, cirrus.
SCL_MASKED = [1, 3, 8, 9, 10]

RAW_BANDS = ["B2", "B3", "B4", "B8", "B11"]


def _mask_clouds(img: ee.Image) -> ee.Image:
    scl = img.select("SCL")
    bad = scl.eq(SCL_MASKED[0])
    for value in SCL_MASKED[1:]:
        bad = bad.Or(scl.eq(value))
    return img.updateMask(bad.Not())


def _add_indices(img: ee.Image) -> ee.Image:
    refl = img.select(RAW_BANDS).divide(10000)
    ndvi = refl.normalizedDifference(["B8", "B4"]).rename("NDVI")
    gndvi = refl.normalizedDifference(["B8", "B3"]).rename("GNDVI")
    # Bare Soil Index. B11 (SWIR) est à 20 m, rééchantillonnée à l'export.
    bsi = refl.expression(
        "((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))",
        {
            "SWIR": refl.select("B11"),
            "RED": refl.select("B4"),
            "NIR": refl.select("B8"),
            "BLUE": refl.select("B2"),
        },
    ).rename("BSI")
    return refl.addBands([ndvi, gndvi, bsi])


def composite(region: ee.Geometry, start: str, end: str, max_cloud: float,
              bands: list[str]) -> tuple[ee.Image, ee.Number]:
    """Médiane des images sans nuages sur la période, avec les bandes demandées.

    Renvoie aussi le nombre d'images utilisées, pour écarter les périodes vides.
    """
    collection = (
        ee.ImageCollection(COLLECTION)
        .filterBounds(region)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
        .map(_mask_clouds)
        .map(_add_indices)
    )
    image = collection.median().select(bands).toFloat().clip(region)
    return image, collection.size()
