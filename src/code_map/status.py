"""`code-map status` — artifact freshness report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from code_map.query import EXIT_NO_ARTIFACT, EXIT_STALE


def run_status(*, fmt: str, fail_on_stale: bool) -> None:
    from code_map.manifest import artifact_root, file_content_hash, load_manifest

    repo_root = Path.cwd()
    artifact = artifact_root(repo_root)
    manifest_path = artifact / "manifest.json"
    if not manifest_path.exists():
        print(f"no code map at {artifact} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)

    manifest = load_manifest(manifest_path)
    files_total = len(manifest.files)
    files_changed = 0
    files_missing = 0

    for rel, meta in manifest.files.items():
        src = repo_root / rel
        if not src.exists():
            files_missing += 1
            continue
        if file_content_hash(src) != meta.get("content_hash", ""):
            files_changed += 1

    stale = (files_changed + files_missing) > 0

    info = {
        "artifact_dir": str(artifact),
        "built_at": manifest.last_built,
        "languages": manifest.languages,
        "files_total": files_total,
        "files_changed_since_build": files_changed,
        "files_missing_since_build": files_missing,
        "stale": stale,
    }

    if fmt == "text":
        print(f"artifact_dir: {info['artifact_dir']}")
        print(f"built_at:     {info['built_at']}")
        print(f"languages:    {', '.join(info['languages'])}")
        print(f"files_total:  {info['files_total']}")
        print(f"files_changed_since_build: {info['files_changed_since_build']}")
        print(f"files_missing_since_build: {info['files_missing_since_build']}")
        print(f"stale:        {info['stale']}")
    else:
        print(json.dumps(info, indent=2))

    if stale and fail_on_stale:
        sys.exit(EXIT_STALE)
