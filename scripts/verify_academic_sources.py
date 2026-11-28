"""Check submitted course materials and the original UI against their archived hashes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = (
    "00_course_project_brief",
    "01_assignment_1_submitted",
    "02_assignment_2_submitted",
    "03_assignment_3_submitted",
)


def main():
    manifest = json.loads((ROOT / "SOURCE_MANIFEST_SHA256.json").read_text(encoding="utf-8"))
    references = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    paths = [f"docs/01_requirements/{name}.{ext}" for name in SUBMISSIONS for ext in ("pdf", "txt")]
    paths.append("prototype/smart-emobility-clean-ui.html")
    failed = False
    for path in paths:
        try:
            digest = hashlib.sha256()
            with (ROOT / path).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            matches = digest.hexdigest() == references[path]
        except (OSError, KeyError) as error:
            print(f"{path}: {error}")
            failed = True
            continue
        print(f"{'OK' if matches else 'CHECKSUM MISMATCH'}  {path}")
        failed |= not matches
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
