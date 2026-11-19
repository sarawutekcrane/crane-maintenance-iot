"""R8 PRE-UAT (Owner source approval Rev 1, Decision 2) — offline, deterministic extractor
for the Owner-supplied repair code workbook `Repair_Code_3_Levels_Reviewed_S01-S05.xlsx`.

NOT imported by the application. Run with any Python that has openpyxl (the backend
does not depend on it):

    python -I scripts/extract_repair_catalogue.py <path-to-xlsx> \
        app/data/repair_catalogue/repair_code_3_levels_reviewed_s01_s05.source.json

Every non-empty row of every sheet is kept raw: cell values as text, the sheet index
and name, and the 1-based row number. No code is invented, remapped or normalized; the
application derives the TEST candidate subset from this raw extract by a fixed rule.
The output records the workbook SHA-256 and a SHA-256 of the canonical extracted rows,
so the loader can detect any later edit.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXTRACTOR_VERSION = "1"
EXPECTED_SOURCE_SHA256 = "eec029991568c63a41ef21e3ee1afdcd525ea5392d24eb5bcafdd6a9cfed1560"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def extract(xlsx: Path) -> dict[str, object]:
    import openpyxl  # offline tool only

    digest = hashlib.sha256(xlsx.read_bytes()).hexdigest()
    if digest != EXPECTED_SOURCE_SHA256:
        raise SystemExit(f"workbook SHA-256 {digest} is not the Owner-supplied file {EXPECTED_SOURCE_SHA256}")
    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    sheets = []
    for index, sheet in enumerate(workbook.worksheets):
        rows = []
        for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = ["" if v is None else str(v) for v in values]
            while cells and cells[-1] == "":
                cells.pop()
            if any(c != "" for c in cells):
                rows.append({"row": number, "cells": cells})
        sheets.append({"index": index, "name": sheet.title, "rows": rows})
    return {
        "source_file": "Repair_Code_3_Levels_Reviewed_S01-S05.xlsx",
        "source_sha256": digest,
        "extractor_version": EXTRACTOR_VERSION,
        "status_note": "Owner-supplied reviewed/proposed dictionary. Used as the TEST source only "
                       "(Owner Decision 2, 2026-11-18); NOT an approved REAL taxonomy.",
        "sheets": sheets,
        "extract_sha256": hashlib.sha256(canonical(sheets).encode("utf-8")).hexdigest(),
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    payload = extract(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {sys.argv[2]}: {sum(len(s['rows']) for s in payload['sheets'])} rows, "
          f"extract_sha256={payload['extract_sha256']}")


if __name__ == "__main__":
    main()
