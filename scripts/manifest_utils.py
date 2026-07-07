"""
Shared helpers for run provenance tracking (archive_run.py, diff_configs.py,
extract_runs.py, and the Streamlit "Scenario Provenance & Report" tab).

Nothing here touches or copies solved .nc network files -- they stay exactly
where PyPSA-AT wrote them. We only ever store lightweight fingerprints
(size/mtime/optional hash) plus a copy of the (small) YAML config that
produced them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

import yaml


def get_git_commit(repo_root: Path) -> Optional[str]:
    """Return the short git commit hash for repo_root, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def file_fingerprint(path: Path, hash_bytes: bool = False, chunk_size: int = 1 << 20) -> dict:
    """Lightweight identity of a (possibly huge) result file without copying it."""
    stat = path.stat()
    info = {
        "size_bytes": stat.st_size,
        "modified_at": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }
    if hash_bytes:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        info["sha256"] = h.hexdigest()
    return info


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def find_runs(runs_dir: Path) -> list[dict]:
    """Load every runs/<tag>/manifest.yaml found, newest first."""
    manifests = []
    if not runs_dir.exists():
        return manifests
    for manifest_path in sorted(runs_dir.glob("*/manifest.yaml")):
        try:
            m = load_yaml(manifest_path)
            m["_manifest_path"] = str(manifest_path)
            m["_run_dir"] = str(manifest_path.parent)
            manifests.append(m)
        except Exception as e:
            print(f"[Warning] Could not parse {manifest_path}: {e}")
    manifests.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return manifests
