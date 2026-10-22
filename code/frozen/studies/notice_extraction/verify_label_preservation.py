'Compare saved label files with their source hashes.'
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def verify(root: Path | None = None) -> dict:
    root = HERE if root is None else root
    manifest = json.loads((root / 'label_specification_PRESERVATION_MANIFEST.json').read_text())
    checked = {}
    for name, expected in manifest["original_files_sha256"].items():
        retained = manifest["original_locations_or_archives"][name]
        path = (root / retained).resolve()
        if not path.is_relative_to(root.resolve()):
            raise RuntimeError(f"preservation path outside notice_extraction: {retained}")
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"pre-NRX3 original changed: {name} (retained at {retained})")
        checked[name] = retained
    return {"state": "PASS_PRE_NRX3_BYTES_PRESERVED", "original_files_verified": len(checked),
            "original_locations_or_archives": checked}


if __name__ == "__main__":
    result = verify()
    print(json.dumps({key: result[key] for key in ("state", "original_files_verified")}))
