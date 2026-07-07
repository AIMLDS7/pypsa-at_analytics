"""
diff_configs.py
===============
Deep-diff the config YAMLs of two archived runs (see archive_run.py) and
produce a flat "what changed" table -- the objective, factual half of
scenario provenance. Pair this with the free-text `notes` field in each
run's manifest.yaml for the "why".

Usage
-----
    python scripts/diff_configs.py --base baseline_2025.04 --target high_h2_electrolysis

    # or diff two raw yaml files directly, ignoring the runs/ archive:
    python scripts/diff_configs.py --base-file config/config.at.yaml --target-file /path/to/other.yaml

Produces a pandas DataFrame with columns:
    parameter_path | change_type | base_value | target_value
and, if run as __main__, also writes it to data/config_diff_<base>_vs_<target>.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from deepdiff import DeepDiff

from manifest_utils import load_yaml, find_runs

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
DATA_DIR = REPO_ROOT / "data"


def _merge_run_configs(config_dir: Path) -> dict:
    """Merge all *.yaml files in a config snapshot dir into a single dict,
    namespaced by filename so keys never collide (e.g. 'config.at.yaml' vs
    'scenarios.manual.yaml')."""
    merged = {}
    for yaml_path in sorted(config_dir.glob("*.yaml")):
        merged[yaml_path.stem] = load_yaml(yaml_path)
    return merged


def _path_to_str(deepdiff_path: str) -> str:
    """Convert DeepDiff's root['a']['b'][0] style path into a readable dotted path."""
    cleaned = deepdiff_path.replace("root", "").replace("']['", ".").replace("['", "").replace("']", "")
    cleaned = cleaned.replace("[", ".").replace("]", "")
    return cleaned.lstrip(".")


def diff_config_dicts(base_cfg: dict, target_cfg: dict) -> pd.DataFrame:
    diff = DeepDiff(base_cfg, target_cfg, ignore_order=True, view="tree")

    rows = []

    for change in diff.get("values_changed", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "value_changed",
            "base_value": change.t1,
            "target_value": change.t2,
        })
    for change in diff.get("dictionary_item_added", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "added_in_target",
            "base_value": None,
            "target_value": change.t2,
        })
    for change in diff.get("dictionary_item_removed", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "removed_in_target",
            "base_value": change.t1,
            "target_value": None,
        })
    for change in diff.get("iterable_item_added", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "list_item_added",
            "base_value": None,
            "target_value": change.t2,
        })
    for change in diff.get("iterable_item_removed", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "list_item_removed",
            "base_value": change.t1,
            "target_value": None,
        })
    for change in diff.get("type_changes", []):
        rows.append({
            "parameter_path": _path_to_str(change.path()),
            "change_type": "type_changed",
            "base_value": change.t1,
            "target_value": change.t2,
        })

    df = pd.DataFrame(rows, columns=["parameter_path", "change_type", "base_value", "target_value"])
    if not df.empty:
        df = df.sort_values("parameter_path").reset_index(drop=True)
    return df


def diff_runs(base_tag: str, target_tag: str) -> pd.DataFrame:
    base_dir = RUNS_DIR / base_tag / "config"
    target_dir = RUNS_DIR / target_tag / "config"
    if not base_dir.exists():
        raise FileNotFoundError(f"No archived config found for run '{base_tag}' at {base_dir}")
    if not target_dir.exists():
        raise FileNotFoundError(f"No archived config found for run '{target_tag}' at {target_dir}")

    base_cfg = _merge_run_configs(base_dir)
    target_cfg = _merge_run_configs(target_dir)
    return diff_config_dicts(base_cfg, target_cfg)


def main():
    parser = argparse.ArgumentParser(description="Diff config YAMLs between two archived runs.")
    parser.add_argument("--base", type=str, help="Base run tag (folder name under runs/).")
    parser.add_argument("--target", type=str, help="Target run tag (folder name under runs/).")
    parser.add_argument("--base-file", type=str, help="Alternative: path to a single base YAML file.")
    parser.add_argument("--target-file", type=str, help="Alternative: path to a single target YAML file.")
    parser.add_argument("--list-runs", action="store_true", help="List all archived run tags and exit.")
    args = parser.parse_args()

    if args.list_runs:
        for m in find_runs(RUNS_DIR):
            print(f"- {m.get('run_tag')}  (created {m.get('created_at')})  notes: {m.get('notes', '')[:80]}")
        return

    if args.base_file and args.target_file:
        base_cfg = {"config": load_yaml(Path(args.base_file))}
        target_cfg = {"config": load_yaml(Path(args.target_file))}
        df = diff_config_dicts(base_cfg, target_cfg)
        out_name = f"config_diff_{Path(args.base_file).stem}_vs_{Path(args.target_file).stem}.csv"
    elif args.base and args.target:
        df = diff_runs(args.base, args.target)
        out_name = f"config_diff_{args.base}_vs_{args.target}.csv"
    else:
        parser.error("Provide either --base/--target run tags, or --base-file/--target-file paths, or --list-runs.")
        return

    print(f"\n{'='*90}\nCONFIG DIFF: {len(df)} parameter(s) changed\n{'='*90}")
    if df.empty:
        print("No differences found -- configs are identical.")
    else:
        print(df.to_string(index=False))

    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / out_name
    df.to_csv(out_path, index=False)
    print(f"\nSaved diff table to {out_path}")


if __name__ == "__main__":
    main()
