'Check the hashes of the saved window extraction records.'
from pathlib import Path
import json
from prepare_notice_scope import sha_file

HERE = Path(__file__).resolve().parent


def verify(root: Path = HERE) -> dict:
    manifest = json.loads((root / 'window_specification_PRESERVATION_MANIFEST.json').read_text())
    for name, record in manifest["original_files"].items():
        path = root / record["retained_path"]
        if not path.is_file() or sha_file(path) != record["sha256"]:
            raise RuntimeError(f"pre-NRX4 artifact changed: {name} -> {path}")
    return {"state": "PASS_ALL_PRE_NRX4_ARTIFACTS_PRESERVED",
            "original_files_verified": len(manifest["original_files"]),
            "original_locations_or_archives": manifest["original_locations_or_archives"],
            "model_calls": 0}


if __name__ == "__main__":
    result = verify()
    result.pop("original_locations_or_archives")
    print(json.dumps(result, sort_keys=True))
