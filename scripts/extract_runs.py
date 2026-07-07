from pathlib import Path
import pypsa
import pandas as pd
import numpy as np
import warnings

# Force Pandas to use standard NumPy object arrays to ensure clean Xarray/Linopy compatibility
pd.options.mode.string_storage = "python"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

RESULTS_DIR = Path("results")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

def extract_comprehensive_telemetry():
    nc_files = list(RESULTS_DIR.glob("*.nc"))
    if not nc_files:
        print(f"[Error] No .nc files found in {RESULTS_DIR}")
        return

    summary_list = []
    fleet_list = []
    dispatch_list = []
    bess_soc_list = []
    hourly_prices_list = []
    lines_summary_list = []
    buses_summary_list = []

    print(f"Executing enterprise telemetry extraction across {len(nc_files)} scenarios...")

    for file_path in nc_files:
        scenario_name = file_path.stem
        print(f"  -> Deep processing & auditing: {scenario_name}")
        
        n = pypsa.Network(str(file_path))
        
        # 1. System Telemetry & Solver Provenance
        total_cost = n.objective if hasattr(n, "objective") else np.nan
        total_load = n.loads_t.p_set.sum().sum() if not n.loads_t.p_set.empty else 0.0
        gen_totals = n.generators_t.p.sum()
        gen_by_carrier = gen_totals.groupby(n.generators.carrier).sum()
        total_gen = gen_by_carrier.sum()
        
        grid_losses_mwh = max(0.0, total_gen - total_load)
        loss_pct = (grid_losses_mwh / total_gen * 100.0) if total_gen > 0 else 0.0
        
        # High-voltage line capacity summary
        high_v_lines = n.lines[n.lines["v_nom"] >= 110] if "v_nom" in n.lines.columns else n.lines
        total_s_nom = high_v_lines["s_nom"].sum() if not high_v_lines.empty else 0.0
        
        summary_list.append({
            "scenario": scenario_name,
            "total_system_cost_eur": total_cost,
            "total_demand_mwh": total_load,
            "total_generation_mwh": total_gen,
            "grid_losses_mwh": grid_losses_mwh,
            "grid_loss_pct": loss_pct,
            "total_ac_line_capacity_mva": total_s_nom,
            "pv_mwh": gen_by_carrier.get("Solar", 0.0) + gen_by_carrier.get("solar", 0.0),
            "wind_mwh": gen_by_carrier.get("Onshore Wind", 0.0) + gen_by_carrier.get("onwind", 0.0),
            "solver_status": "Optimal (Converged)" if not np.isnan(total_cost) else "Warning/Infeasible"
        })

        # 2. Baseline Infrastructure Fleet (Installed P_nom Capacities in MW)
        if not n.generators.empty:
            gen_pnom = n.generators.groupby("carrier")["p_nom"].sum().reset_index()
            gen_pnom.columns = ["carrier", "installed_p_nom_mw"]
            gen_pnom["scenario"] = scenario_name
            fleet_list.append(gen_pnom)

        # 3. Hourly Dispatch Profiles
        if not n.generators_t.p.empty:
            hourly_gen = n.generators_t.p.T.groupby(n.generators.carrier).sum().T
            hourly_gen["scenario"] = scenario_name
            hourly_gen["snapshot"] = n.snapshots
            dispatch_list.append(hourly_gen.melt(id_vars=["scenario", "snapshot"], var_name="carrier", value_name="dispatch_mw"))

        # 4. Battery Energy Storage System (BESS) State of Charge (SoC)
        if not n.stores_t.e.empty:
            battery_stores = n.stores[n.stores.carrier == "battery"].index if "carrier" in n.stores.columns else n.stores.index
            if len(battery_stores) > 0:
                soc_hourly = n.stores_t.e[battery_stores].sum(axis=1).reset_index()
                soc_hourly.columns = ["snapshot", "state_of_charge_mwh"]
                soc_hourly["scenario"] = scenario_name
                bess_soc_list.append(soc_hourly)

        # 5. Hourly Electrical Nodal Prices for Monotonic Duration Curves
        if not n.buses_t.marginal_price.empty:
            ac_buses = [b for b in n.buses.index if len(str(b)) <= 6 and ("AT" in str(b) or "DE" in str(b))]
            if ac_buses:
                ac_prices = n.buses_t.marginal_price[ac_buses].mean(axis=1).reset_index()
                ac_prices.columns = ["snapshot", "mean_electrical_lmp_eur_mwh"]
                ac_prices["scenario"] = scenario_name
                hourly_prices_list.append(ac_prices)

        # 6. Transmission Line Corridor Audit
        if not high_v_lines.empty and not n.lines_t.p0.empty:
            flows_abs = n.lines_t.p0[high_v_lines.index].abs()
            s_noms = high_v_lines["s_nom"]
            util = (flows_abs / s_noms) * 100.0
            
            lines_summary_list.append(pd.DataFrame({
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
                "Congested_Hours_90Pct": (util >= 90.0).sum()
            }))

        # 7. Nodal LMP Audit
        if not n.buses_t.marginal_price.empty:
            bus_lmps = n.buses_t.marginal_price
            buses_summary_list.append(pd.DataFrame({
                "scenario": scenario_name,
                "Bus_ID": n.buses.index.astype(str),
                "Voltage_kV": n.buses["v_nom"] if "v_nom" in n.buses.columns else np.nan,
                "Mean_LMP_EUR_MWh": bus_lmps.mean(),
                "Max_LMP_EUR_MWh": bus_lmps.max(),
                "Price_Volatility_Std": bus_lmps.std()
            }))

    # Write compiled columnar stores to Parquet
    print("Exporting optimized telemetry datasets to /data...")
    pd.DataFrame(summary_list).to_parquet(DATA_DIR / "kpi_summary.parquet", index=False)
    if fleet_list:
        pd.concat(fleet_list, ignore_index=True).to_parquet(DATA_DIR / "fleet_summary.parquet", index=False)
    if dispatch_list:
        pd.concat(dispatch_list, ignore_index=True).to_parquet(DATA_DIR / "hourly_dispatch.parquet", index=False)
    if bess_soc_list:
        pd.concat(bess_soc_list, ignore_index=True).to_parquet(DATA_DIR / "bess_soc.parquet", index=False)
    if hourly_prices_list:
        pd.concat(hourly_prices_list, ignore_index=True).to_parquet(DATA_DIR / "hourly_prices.parquet", index=False)
    if lines_summary_list:
        pd.concat(lines_summary_list, ignore_index=True).to_parquet(DATA_DIR / "lines_summary.parquet", index=False)
    if buses_summary_list:
        pd.concat(buses_summary_list, ignore_index=True).to_parquet(DATA_DIR / "buses_summary.parquet", index=False)
        
    print("ETL Telemetry Extraction Complete!")

if __name__ == "__main__":
    extract_comprehensive_telemetry()