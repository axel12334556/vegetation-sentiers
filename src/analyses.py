"""Analyses du carnet : NDVI, évolution entre deux étés, distance aux sentiers, indice de sol nu.

Les calculs se font côté Google Earth Engine. Seuls de petits résultats reviennent dans Python
(tableaux, vignettes PNG), pour que le carnet reste léger et lisible directement sur GitHub.
"""

from __future__ import annotations

import io
import urllib.request

import ee
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize

COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
ETE = ("06-15", "09-01")  # du 15 juin au 31 août (fin exclue)

# Classes SCL de Sentinel-2 conservées : 4 = végétation, 5 = sol nu.
# Tout le reste (nuages, ombres, eau, neige) est masqué.
SCL_GARDEES = (4, 5)

# Pour les images en couleurs naturelles, on garde la ville, l'eau, les routes : on ne masque
# que les ombres (3), les nuages (8, 9, 10) et la neige (11).
SCL_RGB_MASQUEES = (3, 8, 9, 10, 11)

# Palettes (accessibles aux daltoniens) et bornes d'affichage.
VIS_NDVI = {"min": 0.0, "max": 0.8, "palette": ["#ffffe5", "#d9f0a3", "#78c679", "#238443", "#004529"]}
VIS_EVOLUTION = {"min": -0.2, "max": 0.2, "palette": ["#8c510a", "#d8b365", "#f5f5f5", "#5ab4ac", "#01665e"]}
VIS_BSI = {"min": -0.3, "max": 0.2, "palette": ["#fff7ec", "#fdd49e", "#fc8d59", "#d7301f", "#7f0000"]}
VIS_RGB = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.2}  # couleurs naturelles


# --------------------------------------------------------------------------- géométries

def polygone(anneau: list[list[float]]) -> ee.Geometry:
    """Polygone Earth Engine à partir d'un anneau [[lon, lat], ...] (voir src.config.Zone)."""
    return ee.Geometry.Polygon([anneau])


def masquer_zone(image: ee.Image, exclusion: ee.Geometry | None) -> ee.Image:
    """Masque les pixels situés dans une zone à exclure (incendie, chantier, repousse...)."""
    if exclusion is None:
        return image
    garde = ee.Image(1).paint(ee.FeatureCollection([ee.Feature(exclusion)]), 0)
    return image.updateMask(garde)


# --------------------------------------------------------------------------- composites

def _masque_scl(img: ee.Image) -> ee.Image:
    scl = img.select("SCL")
    garde = scl.eq(SCL_GARDEES[0])
    for valeur in SCL_GARDEES[1:]:
        garde = garde.Or(scl.eq(valeur))
    return img.updateMask(garde)


def _indices(img: ee.Image) -> ee.Image:
    r = img.select(["B2", "B3", "B4", "B8", "B11"]).divide(10000)
    ndvi = r.normalizedDifference(["B8", "B4"]).rename("NDVI")
    gndvi = r.normalizedDifference(["B8", "B3"]).rename("GNDVI")
    # Bare Soil Index. B11 (SWIR) est native à 20 m.
    bsi = r.expression(
        "((S + R) - (N + B)) / ((S + R) + (N + B))",
        {"S": r.select("B11"), "R": r.select("B4"), "N": r.select("B8"), "B": r.select("B2")},
    ).rename("BSI")
    return ee.Image.cat([ndvi, gndvi, bsi])


def collection_saison(region: ee.Geometry, annee: int, saison=ETE, max_nuages: float = 40) -> ee.ImageCollection:
    debut, fin = saison
    return (
        ee.ImageCollection(COLLECTION)
        .filterBounds(region)
        .filterDate(f"{annee}-{debut}", f"{annee}-{fin}")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_nuages))
        .map(_masque_scl)
        .map(_indices)
    )


def composite_saison(region: ee.Geometry, annee: int, saison=ETE, max_nuages: float = 40) -> ee.Image:
    """Médiane des indices NDVI, GNDVI et BSI sur la saison, découpée sur la zone."""
    return collection_saison(region, annee, saison, max_nuages).median().clip(region)


def composite_rgb(region: ee.Geometry, annee: int, saison=ETE, max_nuages: float = 40) -> ee.Image:
    """Médiane des bandes rouge, verte, bleue sur la saison (couleurs naturelles, nuages et ombres masqués)."""
    debut, fin = saison

    def masque(img):
        scl = img.select("SCL")
        nuageux = scl.eq(SCL_RGB_MASQUEES[0])
        for valeur in SCL_RGB_MASQUEES[1:]:
            nuageux = nuageux.Or(scl.eq(valeur))
        return img.updateMask(nuageux.Not())

    return (
        ee.ImageCollection(COLLECTION)
        .filterBounds(region)
        .filterDate(f"{annee}-{debut}", f"{annee}-{fin}")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_nuages))
        .map(masque)
        .select(["B4", "B3", "B2"])
        .median()
        .clip(region)
    )


def evolution(region: ee.Geometry, annee_avant: int, annee_apres: int, bande: str = "NDVI",
              saison=ETE, max_nuages: float = 40) -> ee.Image:
    """Différence apres - avant d'un indice (négatif = baisse)."""
    avant = composite_saison(region, annee_avant, saison, max_nuages).select(bande)
    apres = composite_saison(region, annee_apres, saison, max_nuages).select(bande)
    return apres.subtract(avant).rename(f"d{bande}")


def nombre_images(regions: dict[str, ee.Geometry], annees, saison=ETE, max_nuages: float = 40) -> pd.DataFrame:
    """Tableau zones x années du nombre d'images Sentinel-2 utilisables."""
    requete = ee.Dictionary({
        f"{nom}|{a}": collection_saison(reg, a, saison, max_nuages).size()
        for nom, reg in regions.items() for a in annees
    }).getInfo()
    lignes = [{"zone": k.split("|")[0], "annee": int(k.split("|")[1]), "images": v} for k, v in requete.items()]
    return pd.DataFrame(lignes).pivot(index="zone", columns="annee", values="images")


# --------------------------------------------------------------------------- statistiques

def _reduire(image: ee.Image, reducer: ee.Reducer, region: ee.Geometry, scale: int = 10) -> ee.Dictionary:
    return image.reduceRegion(reducer=reducer, geometry=region, scale=scale, maxPixels=int(1e10), tileScale=4)


def statistiques(image: ee.Image, bande: str, region: ee.Geometry, scale: int = 10) -> dict:
    """Moyenne, écart-type, quantiles et nombre de pixels d'une bande sur la zone."""
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    d = _reduire(image.select(bande), reducer, region, scale).getInfo()
    return {
        "moyenne": d.get(f"{bande}_mean"),
        "ecart_type": d.get(f"{bande}_stdDev"),
        "p10": d.get(f"{bande}_p10"),
        "mediane": d.get(f"{bande}_p50"),
        "p90": d.get(f"{bande}_p90"),
        "pixels": d.get(f"{bande}_count"),
    }


def parts_changement(diff: ee.Image, region: ee.Geometry, seuil_baisse: float = -0.1,
                     seuil_perturbation: float = 0.2, scale: int = 10) -> dict:
    """Part des pixels en forte baisse, et part des pixels très perturbés (|évolution| > seuil)."""
    img = ee.Image.cat([
        diff.lt(seuil_baisse).rename("baisse"),
        diff.abs().gt(seuil_perturbation).rename("perturbe"),
    ])
    d = _reduire(img, ee.Reducer.mean(), region, scale).getInfo()
    return {"part_forte_baisse": d.get("baisse"), "part_perturbee": d.get("perturbe")}


def histogramme(image: ee.Image, bande: str, region: ee.Geometry, mini: float, maxi: float,
                classes: int = 50, scale: int = 20) -> pd.DataFrame:
    h = _reduire(image.select(bande), ee.Reducer.fixedHistogram(mini, maxi, classes), region, scale).getInfo()
    valeurs = np.array(h[bande])
    return pd.DataFrame({"valeur": valeurs[:, 0], "pixels": valeurs[:, 1]})


# --------------------------------------------------------------------------- sentiers

def distance_sentiers(sentiers: ee.FeatureCollection, region: ee.Geometry, rayon: int = 150) -> ee.Image:
    """Distance (m) de chaque pixel au sentier le plus proche, masquée au-delà du rayon."""
    return sentiers.distance(searchRadius=rayon, maxError=1).clip(region).rename("distance")


def groupes_vers_tableau(groupes: list[dict], pas: int) -> pd.DataFrame:
    """Convertit la sortie d'un reducer groupé par classe de distance en tableau trié."""
    lignes = [
        {"distance_m": g["classe"] * pas + pas / 2, "moyenne": g.get("mean"), "pixels": g.get("count")}
        for g in groupes
    ]
    return pd.DataFrame(lignes, columns=["distance_m", "moyenne", "pixels"]).sort_values("distance_m").reset_index(drop=True)


def profil_distance(image: ee.Image, bande: str, distance: ee.Image, region: ee.Geometry,
                    pas: int = 10, scale: int = 10) -> pd.DataFrame:
    """Valeur moyenne d'une bande par classe de distance au sentier (0-10 m, 10-20 m, ...)."""
    classe = distance.divide(pas).floor().int().rename("classe")
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True).group(groupField=1, groupName="classe")
    res = _reduire(image.select(bande).addBands(classe), reducer, region, scale).getInfo()
    return groupes_vers_tableau(res.get("groups", []), pas)


def sentier_vs_temoin(image: ee.Image, bande: str, distance: ee.Image, region: ee.Geometry,
                      proche: float = 15, temoin: tuple[float, float] = (50, 100), scale: int = 10) -> dict:
    """Compare la moyenne d'une bande près des sentiers et dans une bande témoin plus éloignée."""
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    img = image.select(bande)
    masque_proche = distance.lte(proche)
    masque_temoin = distance.gt(temoin[0]).And(distance.lte(temoin[1]))
    d = ee.Dictionary({
        "proche": _reduire(img.updateMask(masque_proche), reducer, region, scale),
        "temoin": _reduire(img.updateMask(masque_temoin), reducer, region, scale),
    }).getInfo()
    p_moy, t_moy = d["proche"].get(f"{bande}_mean"), d["temoin"].get(f"{bande}_mean")
    return {
        "sentier_moyenne": p_moy,
        "sentier_pixels": d["proche"].get(f"{bande}_count"),
        "temoin_moyenne": t_moy,
        "temoin_pixels": d["temoin"].get(f"{bande}_count"),
        "ecart_sentier_moins_temoin": None if p_moy is None or t_moy is None else p_moy - t_moy,
    }


# --------------------------------------------------------------------------- robustesse

def part_baisse_sentier_temoin(diff: ee.Image, distance: ee.Image, region: ee.Geometry, seuil: float = -0.1,
                               proche: float = 15, temoin: tuple[float, float] = (50, 100)) -> dict:
    """Part des pixels en forte baisse (évolution < seuil) près des sentiers et dans la bande témoin.

    Le rapport proche / témoin vaut 1 si les sentiers n'ont pas plus de pixels en forte baisse que le témoin,
    plus de 1 s'ils en ont davantage.
    """
    baisse = diff.lt(seuil).rename("baisse")
    r = sentier_vs_temoin(baisse, "baisse", distance, region, proche, temoin)
    p, t = r["sentier_moyenne"], r["temoin_moyenne"]
    return {
        "part_baisse_sentier": p,
        "part_baisse_temoin": t,
        "rapport_sentier_sur_temoin": None if not p or not t else p / t,
        "pixels_sentier": r["sentier_pixels"],
        "pixels_temoin": r["temoin_pixels"],
    }


def ecarts_par_troncon(image: ee.Image, bande: str, sentiers: ee.FeatureCollection, distance: ee.Image,
                       region: ee.Geometry, n: int = 400, longueur_min: float = 100, proche: float = 15,
                       temoin: tuple[float, float] = (50, 100), graine: int = 7,
                       exclusion: ee.Geometry | None = None, scale: int = 10) -> pd.DataFrame:
    """Pour n tronçons tirés au hasard : valeur moyenne près du tronçon et dans son voisinage témoin.

    Le témoin est pris autour du même tronçon (pixels à 50-100 m de tout sentier, donc pas contaminés par
    un autre sentier) : sentier et témoin partagent le même contexte local (altitude, exposition, sol).
    """
    img = image.select(bande)
    bandes = ee.Image.cat([
        img.updateMask(distance.lte(proche)).rename("proche"),
        img.updateMask(distance.gt(temoin[0]).And(distance.lte(temoin[1]))).rename("temoin"),
    ])

    def secteur(f):
        c = f.geometry().centroid(1).coordinates()
        return ee.Feature(f.geometry().buffer(temoin[1], 5), {
            "longueur": f.get("longueur"), "lon": c.get(0), "lat": c.get(1)})

    tirage = _troncons_longs(sentiers, region, longueur_min, exclusion).randomColumn("alea", graine).sort("alea").limit(n)
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    res = bandes.reduceRegions(collection=tirage.map(secteur), reducer=reducer, scale=scale, tileScale=4)
    cols = ["longueur", "lon", "lat", "proche_mean", "proche_count", "temoin_mean", "temoin_count"]
    donnees = res.select(cols, retainGeometry=False).getInfo()["features"]
    df = pd.DataFrame([f["properties"] for f in donnees], columns=cols)
    return df.rename(columns={"proche_mean": "proche", "temoin_mean": "temoin",
                              "proche_count": "pixels_proche", "temoin_count": "pixels_temoin"})


def resumer_troncons(df: pd.DataFrame, pixels_min: int = 3, n_boot: int = 5000, graine: int = 0) -> dict:
    """Écart moyen sentier - témoin sur les tronçons, avec intervalle de confiance à 95 % par bootstrap.

    Le bootstrap rééchantillonne les tronçons (et non les pixels, qui se ressemblent entre voisins) :
    il mesure donc l'incertitude due au choix des tronçons. Si l'intervalle contient 0, l'écart
    ne se distingue pas du bruit.
    """
    d = df.dropna(subset=["proche", "temoin"])
    d = d[(d["pixels_proche"] >= pixels_min) & (d["pixels_temoin"] >= pixels_min)]
    ecarts = (d["proche"] - d["temoin"]).to_numpy(dtype=float)
    if len(ecarts) < 2:
        return {"n_troncons": int(len(ecarts)), "ecart_moyen": None, "ic95_bas": None, "ic95_haut": None,
                "part_troncons_sous_temoin": None, "distingue_de_zero": None}
    rng = np.random.default_rng(graine)
    moyennes = rng.choice(ecarts, size=(n_boot, len(ecarts)), replace=True).mean(axis=1)
    bas, haut = np.percentile(moyennes, [2.5, 97.5])
    return {
        "n_troncons": int(len(ecarts)),
        "ecart_moyen": float(ecarts.mean()),
        "ic95_bas": float(bas),
        "ic95_haut": float(haut),
        "part_troncons_sous_temoin": float((ecarts < 0).mean()),
        "distingue_de_zero": bool(bas > 0 or haut < 0),
    }


def tracer_intervalles(tableau: pd.DataFrame, titre: str, xlabel: str, ax=None):
    """Écart moyen et intervalle à 95 % par zone (colonnes : zone, ecart_moyen, ic95_bas, ic95_haut)."""
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 0.9 * len(tableau) + 1.5))
    y = np.arange(len(tableau))
    x = tableau["ecart_moyen"].to_numpy(dtype=float)
    ax.errorbar(x, y, xerr=[x - tableau["ic95_bas"].to_numpy(dtype=float),
                            tableau["ic95_haut"].to_numpy(dtype=float) - x],
                fmt="o", color="#2c7fb8", ecolor="#2c7fb8", capsize=4)
    ax.axvline(0, color="#999999", linewidth=0.9)
    ax.set_yticks(y, tableau["zone"])
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(titre)
    ax.grid(axis="x", alpha=0.3)
    return ax


# --------------------------------------------------------------------------- plans rapprochés

def _sommets(coordonnees) -> list[tuple[float, float]]:
    """Aplatit les coordonnées d'une géométrie GeoJSON (ligne ou multi-ligne) en liste de (lon, lat)."""
    if coordonnees and isinstance(coordonnees[0], (int, float)):
        return [(coordonnees[0], coordonnees[1])]
    sommets: list[tuple[float, float]] = []
    for element in coordonnees:
        sommets.extend(_sommets(element))
    return sommets


def milieu(geometrie: dict) -> tuple[float, float] | None:
    """Sommet central d'une ligne : il est toujours sur le sentier (le centroïde, lui, peut en sortir)."""
    sommets = _sommets(geometrie.get("coordinates", [])) if geometrie else []
    return sommets[len(sommets) // 2] if sommets else None


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance approchée en mètres entre deux points (lon, lat), suffisante à l'échelle de quelques km."""
    k = 111_320.0
    dx = (a[0] - b[0]) * k * np.cos(np.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * k
    return float(np.hypot(dx, dy))


def espacer(points: list[tuple[float, float]], n: int, ecart_min: float) -> list[tuple[float, float]]:
    """Garde au plus n points, dans l'ordre donné, séparés d'au moins ecart_min mètres."""
    retenus: list[tuple[float, float]] = []
    for p in points:
        if all(distance_m(p, q) >= ecart_min for q in retenus):
            retenus.append(p)
        if len(retenus) == n:
            break
    return retenus


def _troncons_longs(sentiers: ee.FeatureCollection, region: ee.Geometry, longueur_min: float,
                    exclusion: ee.Geometry | None = None) -> ee.FeatureCollection:
    """Tronçons de sentier plus longs que longueur_min (m), avec leur longueur, hors zone exclue."""
    candidats = (
        sentiers.filterBounds(region)
        .map(lambda f: f.set("longueur", f.geometry().length(1)))
        .filter(ee.Filter.gte("longueur", longueur_min))
    )
    if exclusion is not None:
        candidats = candidats.filter(ee.Filter.bounds(exclusion).Not())
    return candidats


def choisir_plans(sentiers: ee.FeatureCollection, region: ee.Geometry, n: int = 10, longueur_min: float = 300,
                  ecart_min: float = 800, graine: int = 7, exclusion: ee.Geometry | None = None) -> pd.DataFrame:
    """Tire n sites au hasard sur les sentiers (graine fixe : mêmes sites à chaque exécution).

    Seuls les sentiers de plus de longueur_min mètres sont retenus, hors zone exclue, et les sites
    sont espacés d'au moins ecart_min mètres pour ne pas montrer dix fois le même endroit.
    """
    candidats = _troncons_longs(sentiers, region, longueur_min, exclusion)
    tirage = candidats.randomColumn("alea", graine).sort("alea").limit(max(10 * n, 100)).getInfo()["features"]

    points, longueurs = [], {}
    for f in tirage:
        p = milieu(f.get("geometry"))
        if p is not None:
            points.append(p)
            longueurs[p] = f["properties"].get("longueur")
    retenus = espacer(points, n, ecart_min)
    return pd.DataFrame(
        {"plan": range(1, len(retenus) + 1),
         "lon": [p[0] for p in retenus], "lat": [p[1] for p in retenus],
         "longueur_sentier_m": [round(longueurs[p]) for p in retenus]}
    )


def fenetre(lon: float, lat: float, demi_cote: float = 300) -> ee.Geometry:
    """Carré de côté 2 x demi_cote mètres centré sur un point."""
    return ee.Geometry.Point([lon, lat]).buffer(demi_cote).bounds()


def planches_sentiers(sites: pd.DataFrame, image: ee.Image, vis: dict, sentiers: ee.FeatureCollection,
                      demi_cote: float = 300, dimensions: int = 480, titre: str | None = None):
    """Une paire de vignettes par site : l'image seule, puis l'image avec le sentier OpenStreetMap.

    Deux sites par ligne. La version sans sentier sert à juger si le sentier se voit réellement.
    """
    lignes = (len(sites) + 1) // 2
    fig, axes = plt.subplots(lignes, 4, figsize=(16, 4.1 * lignes), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for i, site in enumerate(sites.itertuples()):
        zone = fenetre(site.lon, site.lat, demi_cote)
        ligne, col = divmod(i, 2)
        ax_seul, ax_avec = axes[ligne, 2 * col], axes[ligne, 2 * col + 1]
        ax_seul.imshow(vignette(image, vis, zone, dimensions))
        ax_seul.set_title(f"{site.plan} · {site.lat:.4f} N, {site.lon:.4f} E", fontsize=9)
        ax_avec.imshow(vignette(image, vis, zone, dimensions, sentiers))
        ax_avec.set_title(f"{site.plan} · avec le sentier OSM", fontsize=9)
    if titre:
        fig.suptitle(f"{titre} (fenêtres de {2 * demi_cote:.0f} m de côté)", y=1.0)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- figures

def vignette(image: ee.Image, vis: dict, region: ee.Geometry, dimensions: int = 1024,
             sentiers: ee.FeatureCollection | None = None, couleur_sentiers: str = "d7301f") -> np.ndarray:
    """Image PNG statique (tableau numpy) d'une couche, avec les sentiers en surimpression si fournis."""
    rendu = image.visualize(**vis)
    if sentiers is not None:
        rendu = rendu.blend(sentiers.filterBounds(region).style(color=couleur_sentiers, width=1))
    url = rendu.getThumbURL({"region": region, "dimensions": dimensions, "format": "png"})
    with urllib.request.urlopen(url, timeout=120) as reponse:
        donnees = reponse.read()
    from PIL import Image

    return np.array(Image.open(io.BytesIO(donnees)))


def carte(ax, image: ee.Image, vis: dict, region: ee.Geometry, titre: str, legende: str | None = None,
          sentiers: ee.FeatureCollection | None = None, dimensions: int = 1024) -> None:
    """Dessine une couche Earth Engine dans un axe matplotlib, avec sa barre de couleurs."""
    ax.imshow(vignette(image, vis, region, dimensions, sentiers))
    ax.set_title(titre)
    ax.axis("off")
    if legende:
        cmap = LinearSegmentedColormap.from_list("palette", vis["palette"])
        sm = ScalarMappable(norm=Normalize(vis["min"], vis["max"]), cmap=cmap)
        ax.figure.colorbar(sm, ax=ax, shrink=0.7, label=legende)


def tracer_profils(profils: dict[str, pd.DataFrame], titre: str, ylabel: str, ax=None,
                   bandes: tuple[tuple[float, float], ...] = ((0, 15), (50, 100))):
    """Courbes valeur moyenne / distance au sentier, une par zone ou par période."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 4.5))
    ax.axvspan(*bandes[0], color="#e66101", alpha=0.12, label="bande sentier")
    ax.axvspan(*bandes[1], color="#5e3c99", alpha=0.10, label="bande témoin")
    for nom, df in profils.items():
        ax.plot(df["distance_m"], df["moyenne"], marker="o", markersize=3, label=nom)
    if ylabel.lower().startswith("évolution"):
        ax.axhline(0, color="#999999", linewidth=0.8)
    ax.set_xlabel("Distance au sentier le plus proche (m)")
    ax.set_ylabel(ylabel)
    ax.set_title(titre)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return ax
