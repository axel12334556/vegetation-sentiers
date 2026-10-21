"""Affiche l'état des derniers exports Earth Engine.

    python -m src.status --config config/config.yaml
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config
from .export import init_ee


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--limit", type=int, default=30)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = load_config(args.config)
    ee = init_ee(cfg["gee"]["project"])

    try:
        tasks = ee.data.getTaskList()[: args.limit]
        rows = [(t.get("description"), t.get("state"), t.get("error_message", "")) for t in tasks]
    except AttributeError:
        ops = ee.data.listOperations()[: args.limit]
        rows = []
        for op in ops:
            meta = op.get("metadata", {})
            rows.append((meta.get("description"), meta.get("state"), op.get("error", {}).get("message", "")))

    for description, state, error in rows:
        line = f"{state:<10} {description}"
        if error:
            line += f"  -> {error}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
