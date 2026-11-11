"""Lance les exports Sentinel-2 (indices par zone, année et saison) vers Google Drive.

Exemples :
    python -m src.export --config config/config.yaml --dry-run
    python -m src.export --config config/config.yaml
    python -m src.export --config config/config.yaml --zone calanques --year 2024
"""

from __future__ import annotations

import argparse
import sys

from .config import build_jobs, estimate_mb, load_config

ALLOWED_BANDS = {"NDVI", "GNDVI", "BSI", "B2", "B3", "B4", "B8", "B11"}

# États d'une tâche qui signifient « déjà lancée ou terminée » : on ne la relance pas.
ACTIVE_STATES = {"READY", "RUNNING", "COMPLETED", "PENDING", "SUCCEEDED"}


def init_ee(project: str):
    import ee

    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)
    return ee


def existing_task_names(ee) -> set[str]:
    """Descriptions des exports déjà lancés ou terminés (historique récent de GEE)."""
    names = set()
    try:
        for task in ee.data.getTaskList():
            if task.get("state") in ACTIVE_STATES:
                names.add(task.get("description"))
    except AttributeError:
        for op in ee.data.listOperations():
            meta = op.get("metadata", {})
            if meta.get("state") in ACTIVE_STATES:
                names.add(meta.get("description"))
    return names


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--zone", help="Ne traiter qu'une zone")
    p.add_argument("--year", type=int, help="Ne traiter qu'une année")
    p.add_argument("--season", help="Ne traiter qu'une saison")
    p.add_argument("--dry-run", action="store_true", help="Afficher le plan sans contacter Earth Engine")
    p.add_argument("--force", action="store_true", help="Relancer même les exports déjà faits")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config(args.config)

    bands = cfg["export"]["bands"]
    unknown = set(bands) - ALLOWED_BANDS
    if unknown:
        print(f"Bandes inconnues dans la config : {sorted(unknown)}", file=sys.stderr)
        return 2

    jobs = build_jobs(cfg, zone=args.zone, year=args.year, season=args.season)
    if not jobs:
        print("Aucun export ne correspond aux filtres.", file=sys.stderr)
        return 1

    total = sum(estimate_mb(j, cfg) for j in jobs)
    print(f"{len(jobs)} exports prévus, environ {total:,.0f} Mo au total (non compressé).")

    if args.dry_run:
        for j in jobs:
            print(f"  {j.name:<32} {j.start} -> {j.end}  ~{estimate_mb(j, cfg):,.0f} Mo")
        return 0

    ee = init_ee(cfg["gee"]["project"])
    from .sentinel2 import composite

    done = set() if args.force else existing_task_names(ee)
    started = skipped = empty = 0

    for j in jobs:
        if j.name in done:
            print(f"  déjà fait   {j.name}")
            skipped += 1
            continue

        region = ee.Geometry.Polygon([j.zone.ring])
        image, count = composite(region, j.start, j.end, cfg["sentinel2"]["max_cloud_percent"], bands)
        n_images = count.getInfo()
        if n_images == 0:
            print(f"  aucune image {j.name} (trop de nuages ou période vide)")
            empty += 1
            continue

        task = ee.batch.Export.image.toDrive(
            image=image,
            description=j.name,
            folder=cfg["export"]["drive_folder"],
            fileNamePrefix=j.name,
            region=region,
            scale=cfg["export"]["scale"],
            crs=cfg["export"]["crs"],
            maxPixels=int(1e10),
        )
        task.start()
        print(f"  lancé       {j.name} ({n_images} images)")
        started += 1

    print(f"Lancés : {started} · déjà faits : {skipped} · sans image : {empty}")
    print("Suivi : python -m src.status  (ou l'onglet Tasks de l'éditeur de code GEE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
