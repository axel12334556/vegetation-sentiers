# Végétation et sentiers — récupération des images Sentinel-2

Projet PI² n°192 (ESILV / De Vinci Research Center) : mesurer la dégradation de la végétation autour des sentiers de randonnée à partir d'images satellites.

Ce dépôt automatise la première étape : **produire, pour chaque zone, chaque année et chaque saison, une image des indices NDVI, GNDVI et BSI**, sans télécharger les images brutes.

## Principe

```
config/config.yaml  ──►  Google Earth Engine  ──►  Google Drive (dossier vegetation_sentiers/)
 zones, années,           sélection Sentinel-2,       un GeoTIFF par export :
 saisons, indices         masque des nuages,          fontainebleau_2024_ete.tif
                          médiane, NDVI/GNDVI/BSI     calanques_2024_ete.tif …
```

- **Les calculs se font sur les serveurs de Google** : on n'exporte que le résultat, découpé sur la zone.
- **Les images vont dans Google Drive**, jamais dans Git. Git ne contient que le code et la configuration.
- **On compare la même saison d'une année à l'autre** (le NDVI baisse naturellement en hiver).
- Un export déjà lancé ou terminé n'est pas relancé : on peut relancer le script sans risque de doublon (`--force` pour forcer).

## Prérequis (une fois, par la personne qui lance les exports)

1. Un compte Google avec assez d'espace Drive (les exports sont faits dans le Drive de ce compte).
2. Un **projet Google Cloud enregistré pour Earth Engine en usage non commercial** : <https://code.earthengine.google.com/register>. Le niveau par défaut (Community) donne 150 heures de calcul (EECU-heures) par mois, largement assez pour quelques zones.
3. Reporter l'identifiant du projet dans `config/config.yaml` (`gee.project`).

## Démarrage le plus simple : Google Colab

Ouvrir `notebooks/colab_export.ipynb` dans Colab (Fichier › Ouvrir un notebook › GitHub), puis exécuter les cellules dans l'ordre. Rien à installer sur son ordinateur.

## En local

```bash
git clone https://github.com/<organisation>/vegetation-sentiers.git
cd vegetation-sentiers
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
earthengine authenticate

python -m src.export --dry-run          # plan et volume estimé, sans rien lancer
python -m src.export                    # lance tous les exports
python -m src.export --zone calanques --year 2024 --season ete
python -m src.status                    # état des exports
```

Tests hors ligne : `python -m unittest discover tests`

## Configuration (`config/config.yaml`)

| Clé | Rôle |
|---|---|
| `zones` | Une zone = un polygone My Maps (`kml:` vers un .kml/.kmz dans `zones/`) ou une emprise `bbox: [ouest, sud, est, nord]` |
| `years`, `seasons` | Années et saisons à comparer (dates `MM-JJ`, fin exclue) |
| `export.bands` | `NDVI`, `GNDVI`, `BSI` et/ou réflectances brutes `B2 B3 B4 B8 B11` (pour le groupe deep learning) |
| `export.crs`, `export.scale` | Projection (EPSG:4326 par défaut) et pixel en mètres (10) |
| `sentinel2.max_cloud_percent` | Images trop nuageuses écartées avant le masquage pixel par pixel |

Les emprises fournies pour Fontainebleau, les Calanques et le Mont Ventoux sont **approximatives** : remplacez-les par vos polygones.

### Ajouter une zone depuis Google My Maps

1. Dessiner le polygone, puis menu ⋮ › Exporter en KML/KMZ.
2. Déposer le fichier dans `zones/`, par exemple `zones/sugiton.kml`.
3. Ajouter dans `config.yaml` : `sugiton: {kml: "zones/sugiton.kml"}`.

## Volume

Avec les trois emprises par défaut, 7 années et 2 saisons : 42 exports, environ 1 Go au total (`--dry-run` affiche l'estimation). Ajouter les bandes brutes multiplie le volume par environ 2,7.

## Points d'attention

- **Résolution** : un pixel fait 10 m, un sentier 1 à 2 m. On analyse une bande autour du sentier, pas le sentier lui-même.
- **BSI** : il utilise la bande B11, native à 20 m, rééchantillonnée à 10 m à l'export.
- **Nuages** : le masque utilise la classification SCL de Sentinel-2 (nuages, ombres, cirrus). Une période sans image exploitable est signalée et ignorée.
- **Surfaces** : en EPSG:4326 les pixels sont en degrés ; pour mesurer des surfaces en mètres, utiliser EPSG:2154 (Lambert-93).

## Organisation du dépôt

```
config/config.yaml     zones, périodes, indices, dossier Drive
zones/                 polygones My Maps (.kml / .kmz)
src/export.py          lancement des exports
src/status.py          suivi des exports
src/sentinel2.py       composite et indices (côté Earth Engine)
src/config.py          lecture de la config, liste des exports, estimation du volume
src/kml.py             lecture des polygones My Maps
notebooks/             notebook Colab
tests/                 tests hors ligne
```
