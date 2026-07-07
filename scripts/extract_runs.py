"""
extract_runs.py
================
ETL that reads solved PyPSA-AT networks (results/*.nc) and compiles a
long-lived, columnar Parquet telemetry store in data/.

Provenance-aware behaviour
--------------------------
Because results/*.nc gets overwritten every time you re-run PyPSA-AT with a
new/modified config, we do NOT treat data/*.parquet as a disposable cache
tied 1:1 to whatever currently sits in results/. Instead:

  1. Every row extracted is tagged with a `run_tag` column.
     - If runs/<tag>/manifest.yaml (see archive_run.py) records this exact
       .nc file (matched by filename + size fingerprint), that tag is used.
     - Otherwise the row is tagged "unarchived" (you ran extraction without
       first snapshotting a run -- still works, just less traceable).
  2. New extractions are APPENDED to the existing Parquet store (dedup on
     run_tag + scenario), not blindly overwritten. This means once you
     archive_run + extract for "baseline", you can safely let PyPSA-AT
     overwrite results/*.nc for the next scenario, re-run archive_run +
     extract again, and BOTH scenarios remain queryable side by side in
     data/*.parquet and in the dashboard -- even though the original .nc
     files no longer coexist on disk.

Usage
-----
    python scripts/extract_runs.py
    python scripts/extract_runs.py --force-tag manual_experiment_1
    python scripts/extract_runs.py --reset   # wipe and rebuild the store from only what's currently in results/
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from manifest_utils import find_runs

# Force Pandas to use standard NumPy object arrays to ensure clean Xarray/Linopy compatibility
pd.options.mode.string_storage = "python"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
DATA_DIR = REPO_ROOT / "data"
RUNS_DIR = REPO_ROOT / "runs"
DATA_DIR.mkdir(exist_ok=True)

TABLES = [
    "kpi_summary",
    "fleet_summary",
    "hourly_dispatch",
    "bess_soc",
    "hourly_prices",
    "lines_summary",
    "buses_summary",
]


def resolve_run_tag(nc_path: Path, manifests: list[dict]) -> str:
    """Best-effort match of a currently-present .nc file to the run that
    archived it, verified by filename + byte-size fingerprint."""
    stat = nc_path.stat()
    for m in manifests:  # already sorted newest-first by find_runs()
        linked = m.get("linked_results", {}) or {}
        fp = linked.get(nc_path.name)
        if fp and fp.get("size_bytes") == stat.st_size:
            return m["run_tag"]
    return "unarchived"


def extract_single_network(file_path: Path, run_tag: str):
    scenario_name = file_path.stem
    print(f"  -> Deep processing & auditing: [{run_tag}] {scenario_name}")

    n = pypsa.Network(str(file_path))

    out = {t: None for t in TABLES}

    # 1. System Telemetry & Solver Provenance
    total_cost = n.objective if hasattr(n, "objective") else np.nan
    total_load = n.loads_t.p_set.sum().sum() if not n.loads_t.p_set.empty else 0.0
    gen_totals = n.generators_t.p.sum()
    gen_by_carrier = gen_totals.groupby(n.generators.carrier).sum()
    total_gen = gen_by_carrier.sum()

    grid_losses_mwh = max(0.0, total_gen - total_load)
    loss_pct = (grid_losses_mwh / total_gen * 100.0) if total_gen > 0 else 0.0

    high_v_lines = n.lines[n.lines["v_nom"] >= 110] if "v_nom" in n.lines.columns else n.lines
    total_s_nom = high_v_lines["s_nom"].sum() if not high_v_lines.empty else 0.0

    kpi_row = {
        "run_tag": run_tag,
        "scenario": scenario_name,
        "total_system_cost_eur": total_cost,
        "total_demand_mwh": total_load,
        "total_generation_mwh": total_gen,
        "grid_losses_mwh": grid_losses_mwh,
        "grid_loss_pct": loss_pct,
        "total_ac_line_capacity_mva": total_s_nom,
        "pv_mwh": gen_by_carrier.get("Solar", 0.0) + gen_by_carrier.get("solar", 0.0),
        "wind_mwh": gen_by_carrier.get("Onshore Wind", 0.0) + gen_by_carrier.get("onwind", 0.0),
        "solver_status": "Optimal (Converged)" if not np.isnan(total_cost) else "Warning/Infeasible",
    }
    out["kpi_summary"] = pd.DataFrame([kpi_row])

    # 2. Baseline Infrastructure Fleet (Installed P_nom Capacities in MW)
    if not n.generators.empty:
        gen_pnom = n.generators.groupby("carrier")["p_nom"].sum().reset_index()
        gen_pnom.columns = ["carrier", "installed_p_nom_mw"]
        gen_pnom["scenario"] = scenario_name
        gen_pnom["run_tag"] = run_tag
        out["fleet_summary"] = gen_pnom

    # 3. Hourly Dispatch Profiles
    if not n.generators_t.p.empty:
        hourly_gen = n.generators_t.p.T.groupby(n.generators.carrier).sum().T
        hourly_gen["scenario"] = scenario_name
        hourly_gen["run_tag"] = run_tag
        hourly_gen["snapshot"] = n.snapshots
        out["hourly_dispatch"] = hourly_gen.melt(
            id_vars=["scenario", "run_tag", "snapshot"], var_name="carrier", value_name="dispatch_mw"
        )

    # 4. Battery Energy Storage System (BESS) State of Charge (SoC)
    if not n.stores_t.e.empty:
        battery_stores = n.stores[n.stores.carrier == "battery"].index if "carrier" in n.stores.columns else n.stores.index
        if len(battery_stores) > 0:
            soc_hourly = n.stores_t.e[battery_stores].sum(axis=1).reset_index()
            soc_hourly.columns = ["snapshot", "state_of_charge_mwh"]
            soc_hourly["scenario"] = scenario_name
            soc_hourly["run_tag"] = run_tag
            out["bess_soc"] = soc_hourly

    # 5. Hourly Electrical Nodal Prices for Monotonic Duration Curves
    if not n.buses_t.marginal_price.empty:
        ac_buses = [b for b in n.buses.index if len(str(b)) <= 6 and ("AT" in str(b) or "DE" in str(b))]
        if ac_buses:
            ac_prices = n.buses_t.marginal_price[ac_buses].mean(axis=1).reset_index()
            ac_prices.columns = ["snapshot", "mean_electrical_lmp_eur_mwh"]
            ac_prices["scenario"] = scenario_name
            ac_prices["run_tag"] = run_tag
            out["hourly_prices"] = ac_prices

    # 6. Transmission Line Corridor Audit
    if not high_v_lines.empty and not n.lines_t.p0.empty:
        flows_abs = n.lines_t.p0[high_v_lines.index].abs()
        s_noms = high_v_lines["s_nom"]
        util = (flows_abs / s_noms) * 100.0

        out["lines_summary"] = pd.DataFrame({
            "run_tag": run_tag,
            "scenario": scenario_name,
            "Line_ID": high_v_lines.index.astype(str),
            "Bus_0": high_v_lines["bus0"].astype(str),
            "Bus_1": high_v_lines["bus1"].astype(str),
            "Voltage_kV": high_v_lines["v_nom"],
            "Length_km": high_v_lines["length"],
            "Nominal_Capacity_MVA": s_noms,
            "Max_Flow_MW": flows_abs.max(),
            "Peak_Utilization_Pct": util.max(),
            "Mean_Utilization_Pct": util.mean(),
            "Congested_Hours_90Pct": (util >= 90.0).sum(),
        })

    # 7. Nodal LMP Audit
    if not n.buses_t.marginal_price.empty:
        bus_lmps = n.buses_t.marginal_price
        out["buses_summary"] = pd.DataFrame({
            "run_tag": run_tag,
            "scenario": scenario_name,
            "Bus_ID": n.buses.index.astype(str),
            "Voltage_kV": n.buses["v_nom"] if "v_nom" in n.buses.columns else np.nan,
            "Mean_LMP_EUR_MWh": bus_lmps.mean(),
            "Max_LMP_EUR_MWh": bus_lmps.max(),
            "Price_Volatility_Std": bus_lmps.std(),
        })

    return out


def append_and_dedup(table_name: str, new_df: pd.DataFrame, reset: bool):
    """Merge new_df into the existing Parquet store for this table, replacing
    any prior rows that share the same (run_tag, scenario) so re-running
    extraction for the same run is idempotent, while older archived runs are
    preserved untouched."""
    path = DATA_DIR / f"{table_name}.parquet"
    if not reset and path.exists():
        existing = pd.read_parquet(path)
        key_cols = [c for c in ("run_tag", "scenario") if c in existing.columns]
        if key_cols:
            new_keys = new_df[key_cols].drop_duplicates()
            mask = existing.set_index(key_cols).index.isin(
                pd.MultiIndex.from_frame(new_keys) if len(key_cols) > 1 else new_keys[key_cols[0]]
            )
            existing = existing[~mask]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_parquet(path, index=False)
    return len(combined)


def extract_comprehensive_telemetry(force_tag: str | None = None, reset: bool = False):
    nc_files = list(RESULTS_DIR.glob("*.nc"))
    if not nc_files:
        print(f"[Error] No .nc files found in {RESULTS_DIR}")
        return

    manifests = find_runs(RUNS_DIR)
    if not manifests and not force_tag:
        print("[Notice] No archived runs found under runs/. Extracting with run_tag='unarchived'.\n"
              "         Tip: run scripts/archive_run.py --tag <name> --notes \"...\" BEFORE re-running "
              "PyPSA-AT with a new config, so results stay traceable to the config that produced them.")

    print(f"Executing enterprise telemetry extraction across {len(nc_files)} network file(s)...")

    collected = {t: [] for t in TABLES}

    for file_path in nc_files:
        run_tag = force_tag or resolve_run_tag(file_path, manifests)
        tables = extract_single_network(file_path, run_tag)
        for t in TABLES:
            if tables[t] is not None:
                collected[t].append(tables[t])

    print("Merging into durable Parquet telemetry store in /data (append + dedup by run_tag/scenario)...")
    for t in TABLES:
        if collected[t]:
            new_df = pd.concat(collected[t], ignore_index=True)
            n_rows = append_and_dedup(t, new_df, reset=reset)
            print(f"  {t}.parquet -> {n_rows:,} total rows")

    print("ETL Telemetry Extraction Complete!")


def main():
    parser = argparse.ArgumentParser(description="Extract PyPSA-AT .nc results into the durable Parquet store.")
    parser.add_argument("--force-tag", type=str, default=None,
                         help="Manually tag all currently-found .nc files with this run_tag "
                              "(bypasses auto-matching against runs/*/manifest.yaml).")
    parser.add_argument("--reset", action="store_true",
                         help="Wipe existing Parquet history for touched tables and rebuild from scratch "
                              "using only what's currently in results/.")
    args = parser.parse_args()
    extract_comprehensive_telemetry(force_tag=args.force_tag, reset=args.reset)


if __name__ == "__main__":
    main()
