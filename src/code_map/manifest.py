"""manifest.json reader/writer + content-hash cache + repo-slug derivation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Manifest:
    languages: list[str] = field(default_factory=list)
    grammar_versions: dict[str, str] = field(default_factory=dict)
    last_built: str = ""
    files: dict[str, dict[str, str]] = field(default_factory=dict)


def derive_repo_slug(repo_root: Path) -> str:
    base = repo_root.name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return slug or "repo"


def artifact_root(repo_root: Path) -> Path:
    """Return the artifact directory for a repo.

    - If the repo is Warden-managed (`.warden/` exists), keep the legacy
      `.warden/maps/<slug>/` location for backward compatibility.
    - Otherwise default to `.code-map/` in the repo root.
    """
    if (repo_root / ".warden").exists():
        return repo_root / ".warden" / "maps" / derive_repo_slug(repo_root)
    return repo_root / ".code-map"


def file_content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8")


def load_manifest(path: Path) -> Manifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        languages=raw.get("languages", []),
        grammar_versions=raw.get("grammar_versions", {}),
        last_built=raw.get("last_built", ""),
        files=raw.get("files", {}),
    )
