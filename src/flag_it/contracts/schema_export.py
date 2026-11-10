"""Generate, write, and check the committed JSON Schema files.

    python -m flag_it.contracts.schema_export                     # regenerate after a version bump
    python -m flag_it.contracts.schema_export --init              # first export only
    python -m flag_it.contracts.schema_export --check             # schemas match the models
    python -m flag_it.contracts.schema_export --check --base F    # ...and F (main's manifest) is older
"""

import argparse
import hashlib
import json
from pathlib import Path

from flag_it.contracts import SCHEMA_MODELS
from flag_it.contracts.common import CONTRACT_VERSION, InputModel

SCHEMA_DIR = Path(__file__).parent / "schema"
MANIFEST = "manifest.json"


def generate() -> dict[str, str]:
    files = {}
    for name, model in sorted(SCHEMA_MODELS.items()):
        mode = "validation" if issubclass(model, InputModel) else "serialization"
        files[f"{name}.json"] = json.dumps(model.model_json_schema(mode=mode), indent=2, sort_keys=True) + "\n"
    return files


def fingerprint(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(files[name].encode())
    return digest.hexdigest()


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def _read_manifest(schema_dir: Path) -> dict | None:
    path = schema_dir / MANIFEST
    return json.loads(path.read_text()) if path.exists() else None


def write(schema_dir: Path = SCHEMA_DIR, *, init: bool = False) -> None:
    files = generate()
    new_fingerprint = fingerprint(files)
    manifest = _read_manifest(schema_dir)
    if manifest is None and any(schema_dir.glob("*.json")) and not init:
        raise SystemExit(f"{MANIFEST} is missing but schema files exist. Restore it from git; don't regenerate.")
    if (
        manifest is not None
        and manifest["fingerprint"] != new_fingerprint
        and manifest["contract_version"] == CONTRACT_VERSION
    ):
        raise SystemExit(
            "Schemas changed but CONTRACT_VERSION did not. Bump CONTRACT_VERSION in "
            "src/flag_it/contracts/common.py (see Versioning in docs/contracts.md), then rerun."
        )
    schema_dir.mkdir(parents=True, exist_ok=True)
    for stale in schema_dir.glob("*.json"):
        if stale.name != MANIFEST and stale.name not in files:
            stale.unlink()
    for name, text in files.items():
        (schema_dir / name).write_text(text)
    (schema_dir / MANIFEST).write_text(
        json.dumps({"contract_version": CONTRACT_VERSION, "fingerprint": new_fingerprint}, indent=2) + "\n"
    )


def check(schema_dir: Path = SCHEMA_DIR, *, base_manifest: dict | None = None) -> list[str]:
    files = generate()
    current_fingerprint = fingerprint(files)
    problems = []
    for name, text in files.items():
        path = schema_dir / name
        if not path.exists():
            problems.append(f"missing {name}")
        elif path.read_text() != text:
            problems.append(f"out of date: {name}")
    for path in schema_dir.glob("*.json"):
        if path.name != MANIFEST and path.name not in files:
            problems.append(f"no model for {path.name}")
    manifest = _read_manifest(schema_dir)
    if manifest is None:
        problems.append(f"missing {MANIFEST}")
    else:
        if manifest["contract_version"] != CONTRACT_VERSION:
            problems.append(f"{MANIFEST} has version {manifest['contract_version']}, code has {CONTRACT_VERSION}")
        if manifest["fingerprint"] != current_fingerprint:
            problems.append(f"{MANIFEST} fingerprint is out of date")
    if (
        base_manifest is not None
        and base_manifest["fingerprint"] != current_fingerprint
        and version_tuple(CONTRACT_VERSION) <= version_tuple(base_manifest["contract_version"])
    ):
        problems.append(
            f"schemas differ from main, but CONTRACT_VERSION {CONTRACT_VERSION} is not higher than "
            f"main's {base_manifest['contract_version']}"
        )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m flag_it.contracts.schema_export")
    parser.add_argument("--check", action="store_true", help="only report problems; write nothing")
    parser.add_argument("--base", type=Path, help="with --check: main's manifest.json to compare against")
    parser.add_argument("--init", action="store_true", help="first export, when no manifest exists yet")
    args = parser.parse_args(argv)  # an unknown flag exits with an error instead of writing
    if args.check:
        base = json.loads(args.base.read_text()) if args.base and args.base.exists() else None
        problems = check(SCHEMA_DIR, base_manifest=base)
        for problem in problems:
            print(problem)
        if problems:
            print("Run: python -m flag_it.contracts.schema_export (bump CONTRACT_VERSION first if a model changed)")
        return 1 if problems else 0
    write(SCHEMA_DIR, init=args.init)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
