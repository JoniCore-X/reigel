"""Import a small, explicitly reviewed corporate fact set, without remote APIs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reigel.api import load_environment
from reigel.core import Store
from reigel.knowledge import KnowledgeBase


def main():
    parser = argparse.ArgumentParser(description="Registra una revisión real de las páginas corporativas de Power Solar. No renueva datos automáticamente.")
    parser.add_argument("--source", required=True, choices=("home", "company", "locations"))
    parser.add_argument("--topics", required=True, nargs="+", help="Hechos revisados: services battery process / company / locations")
    parser.add_argument("--reviewed-at", required=True, help="Fecha real de revisión ISO 8601 con zona horaria; no usar la fecha actual si la revisión fue anterior.")
    args = parser.parse_args()
    load_environment()
    try:
        result = KnowledgeBase(Store()).import_reviewed_snapshot(args.source, args.topics, args.reviewed_at)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
