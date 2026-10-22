'Check the hashes of the saved initial label files.'
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def verify() -> dict:
    manifest = json.loads((HERE / "V1_PRESERVATION_MANIFEST.json").read_text())
    checked = {}
    for name, expected in manifest["original_files_sha256"].items():


        relative = manifest["archives"].get(name, "archive_v1/.runner.lock" if name == ".runner.lock" else name)
        path = HERE / relative
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"v1 original bytes changed/missing: {name} (retained at {relative})")
        checked[name] = relative
    return {"state": "PASS_V1_BYTES_PRESERVED", "original_files_verified": len(checked),
            "original_locations_or_archives": checked}


if __name__ == "__main__":
    result = verify()
    print(json.dumps({key: result[key] for key in ("state", "original_files_verified")}))
