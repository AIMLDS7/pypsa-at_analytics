"""
archive_run.py
==============
Snapshot the CURRENT config (config/*.yaml) together with a fingerprint of the
CURRENT results/*.nc files into runs/<run_tag>/, without touching, copying, or
regenerating any .nc network file.

This is the single "checkpoint" command you run each time you finalize a
config + simulation batch, so later you can:
  - diff two runs' configs (scripts/diff_configs.py)
  - trace exactly which config produced which results/*.nc files
  - attach a free-text rationale ("why did we change this?") to the run

Usage
-----
    python scripts/archive_run.py --tag baseline_2025.04 \
        --notes "Initial AT_KN2040 baseline run, AT NUTS3 clustering (3 regions)."

    python scripts/archive_run.py --tag high_h2_electrolysis \
        --notes "Raised H2 Electrolysis min capacity in AT to 2 GW for 2040/2050."

If --tag is omitted, a timestamp-based tag is generated automatically.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from manifest_utils import get_git_commit, file_fingerprint, save_yaml, now_iso

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
RESULTS_DIR = REPO_ROOT / "results"
RUNS_DIR = REPO_ROOT / "runs"


def archive_run(tag: str, notes: str, hash_results: bool = False) -> Path:
    run_dir = RUNS_DIR / tag
    if run_dir.exists():
        raise FileExistsError(
            f"runs/{tag} already exists. Choose a different --tag or delete the old snapshot first."
        )

    # 1. Copy the (small) config YAMLs verbatim -- these are the source of truth.
    config_snapshot_dir = run_dir / "config"
    if CONFIG_DIR.exists():
        shutil.copytree(CONFIG_DIR, config_snapshot_dir)
    else:
        config_snapshot_dir.mkdir(parents=True)
        print(f"[Warning] {CONFIG_DIR} not found -- archiving an empty config snapshot.")

    # 2. Fingerprint (NOT copy) every current results/*.nc so we know exactly
    #    which solved networks this config snapshot corresponds to.
    nc_files = sorted(RESULTS_DIR.glob("*.nc")) if RESULTS_DIR.exists() else []
    result_fingerprints = {}
    for nc in nc_files:
        result_fingerprints[nc.name] = file_fingerprint(nc, hash_bytes=hash_results)

    if not nc_files:
        print(f"[Warning] No .nc files currently found in {RESULTS_DIR}. "
              f"Manifest will record zero linked results (you can re-run archive later).")

    # 3. Write manifest.yaml
    manifest = {
        "run_tag": tag,
        "created_at": now_iso(),
        "git_commit": get_git_commit(REPO_ROOT),
        "notes": notes or "",
        "config_files": sorted(p.name for p in CONFIG_DIR.glob("*.yaml")) if CONFIG_DIR.exists() else [],
        "linked_results": result_fingerprints,
        "results_dir": str(RESULTS_DIR),
    }
    save_yaml(manifest, run_dir / "manifest.yaml")

    print(f"Archived run '{tag}' -> {run_dir}")
    print(f"  Config files snapshotted: {manifest['config_files']}")
    print(f"  Linked result networks:   {list(result_fingerprints.keys())}")
    return run_dir


def main():
    parser = argparse.ArgumentParser(description="Snapshot config + fingerprint results for provenance tracking.")
    parser.add_argument("--tag", type=str, default=None, help="Unique run tag (folder name under runs/).")
    parser.add_argument("--notes", type=str, default="", help="Free-text rationale for this run/config change.")
    parser.add_argument("--hash-results", action="store_true",
                         help="Compute a full SHA-256 hash of each .nc file (slower, but exact integrity check).")
    args = parser.parse_args()

    tag = args.tag or now_iso().replace(":", "").replace("-", "")
    archive_run(tag=tag, notes=args.notes, hash_results=args.hash_results)


if __name__ == "__main__":
    main()
