import pypsa
import pandas as pd
import numpy as np
import warnings

# Force Pandas to use standard Python NumPy object arrays for strings instead of PyArrow
pd.options.mode.string_storage = "python"

# Suppress routine solver and deprecation warnings during automated runs
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

def sanitize_arrow_dtypes(n: pypsa.Network) -> None:
    """
    Deep-scrubs all PyArrow string arrays across static and dynamic PyPSA v1.2+ tables,
    converting them to standard NumPy object arrays while PRESERVING index names.
    """
    components = n.components.values() if hasattr(n, "components") else n.iterate_components()
    
    for c in components:
        # 1. Scrub static table (e.g., n.buses, n.generators, n.lines)
        df = c.static if hasattr(c, "static") else c.df
        if df is not None and not df.empty:
            # Preserve original index metadata (crucial for PyPSA consistency checks!)
            orig_name = df.index.name
            orig_names = df.index.names if isinstance(df.index, pd.MultiIndex) else None
            
            # Force Index to NumPy object array while keeping names intact
            if isinstance(df.index, pd.MultiIndex):
                df.index = pd.MultiIndex.from_tuples(df.index.to_numpy(), names=orig_names)
            else:
                df.index = pd.Index(df.index.to_numpy(dtype=object), name=orig_name)
                
            # Force string/arrow columns to NumPy object array
            for col in df.columns:
                dtype_str = str(df[col].dtype).lower()
                array_str = str(type(df[col].array)).lower() if hasattr(df[col], "array") else ""
                if "arrow" in dtype_str or "string" in dtype_str or df[col].dtype == object:
                    try:
                        df[col] = df[col].to_numpy(dtype=object)
                    except Exception:
                        pass

        # 2. Scrub dynamic time-series tables (e.g., n.generators_t.p)
        dynamic_dict = c.dynamic if hasattr(c, "dynamic") else (c.pnl if hasattr(c, "pnl") else {})
        for attr, df_dyn in dynamic_dict.items():
            if df_dyn is not None and not df_dyn.empty and hasattr(df_dyn, "columns"):
                orig_col_name = df_dyn.columns.name
                if hasattr(df_dyn.columns, "to_numpy"):
                    df_dyn.columns = pd.Index(df_dyn.columns.to_numpy(dtype=object), name=orig_col_name)

def run_comparative_expansion_study(base_network_path: str, target_node: str = None, feeding_line: str = None) -> pd.DataFrame:
    """
    Executes a comparative co-optimization study between Transmission Expansion
    and Local Generation/Storage Expansion to identify the cost-minimal solution.
    """
    # Load baseline network
    n_base = pypsa.Network(base_network_path)
    
    # Auto-detect valid line corridor if placeholder or invalid ID is provided
    if feeding_line not in n_base.lines.index:
        valid_lines = n_base.lines[n_base.lines["v_nom"] >= 110]
        feeding_line = valid_lines.index[0] if not valid_lines.empty else n_base.lines.index[0]
        print(f"[Auto-Detect] Selected feeding line corridor: '{feeding_line}'")
        
    # Auto-detect downstream bus node if placeholder or invalid ID is provided
    if target_node not in n_base.buses.index:
        target_node = n_base.lines.loc[feeding_line, "bus1"]
        print(f"[Auto-Detect] Selected downstream target bus node: '{target_node}'")

    results = {}

    # ---------------------------------------------------------
    # SCENARIO A: TRANSMISSION CO-OPTIMIZATION ONLY
    # ---------------------------------------------------------
    n_trans = pypsa.Network(base_network_path)
    n_trans.sanitize()             # Fix dangling buses and missing carrier metadata
    sanitize_arrow_dtypes(n_trans) # Deep-scrub PyArrow backends while keeping index names
    
    # Freeze all generator capacities
    if not n_trans.generators.empty:
        n_trans.generators["p_nom_extendable"] = False
    
    # Allow expansion exclusively on the targeted grid corridor
    n_trans.lines["s_nom_extendable"] = False
    n_trans.lines.loc[feeding_line, "s_nom_extendable"] = True
    n_trans.lines.loc[feeding_line, "capital_cost"] = 450.0  # Annualized €/MVA/year
    
    print(f"\nSolving Scenario A: Transmission Co-Optimization along '{feeding_line}'...")
    n_trans.optimize(solver_name="highs", include_objective_constant=False)
    
    s_nom_initial = n_trans.lines.loc[feeding_line, "s_nom"]
    s_nom_optimal = n_trans.lines.loc[feeding_line, "s_nom_opt"]
    
    results["Scenario_A_Transmission"] = {
        "Target_Corridor/Node": feeding_line,
        "Total_Objective_Cost_EUR": n_trans.objective,
        "Line_Expansion_Added_MVA": max(0.0, s_nom_optimal - s_nom_initial),
        "Local_PV_Added_MW": 0.0,
        "Local_BESS_Added_MWh": 0.0
    }

    # ---------------------------------------------------------
    # SCENARIO B: LOCAL GENERATION/STORAGE CO-OPTIMIZATION ONLY
    # ---------------------------------------------------------
    n_gen = pypsa.Network(base_network_path)
    n_gen.sanitize()
    sanitize_arrow_dtypes(n_gen)
    
    # Freeze transmission lines
    n_gen.lines["s_nom_extendable"] = False
    if not n_gen.generators.empty:
        n_gen.generators["p_nom_extendable"] = False
    if not n_gen.stores.empty:
        n_gen.stores["e_nom_extendable"] = False
    
    # Identify or create candidate local Solar PV at target node
    local_pv_candidates = n_gen.generators[n_gen.generators["bus"] == target_node]
    if not local_pv_candidates.empty:
        local_pv_id = local_pv_candidates.index[0]
        n_gen.generators.loc[local_pv_id, "p_nom_extendable"] = True
        n_gen.generators.loc[local_pv_id, "capital_cost"] = 35000.0  # Annualized €/MW/year
    else:
        local_pv_id = f"{target_node}_solar_expansion"
        n_gen.add("Generator", local_pv_id, bus=target_node, carrier="solar", p_nom_extendable=True, capital_cost=35000.0)

    # Identify or create candidate local Battery Storage (BESS) at target node
    local_bess_candidates = n_gen.stores[n_gen.stores["bus"] == target_node] if not n_gen.stores.empty else pd.DataFrame()
    if not local_bess_candidates.empty:
        bess_store_id = local_bess_candidates.index[0]
        n_gen.stores.loc[bess_store_id, "e_nom_extendable"] = True
        n_gen.stores.loc[bess_store_id, "capital_cost"] = 28000.0  # Annualized €/MWh/year
    else:
        bess_store_id = f"{target_node}_bess_expansion"
        n_gen.add("Store", bess_store_id, bus=target_node, carrier="battery", e_nom_extendable=True, capital_cost=28000.0)

    # Scrub again after injecting new local assets while preserving names
    sanitize_arrow_dtypes(n_gen)

    print(f"Solving Scenario B: Local Generation/Storage Co-Optimization at node '{target_node}'...")
    n_gen.optimize(solver_name="highs", include_objective_constant=False)
    
    pv_opt = n_gen.generators.loc[local_pv_id, "p_nom_opt"] - n_gen.generators.loc[local_pv_id, "p_nom"] if "p_nom" in n_gen.generators.columns and not pd.isna(n_gen.generators.loc[local_pv_id, "p_nom"]) else n_gen.generators.loc[local_pv_id, "p_nom_opt"]
    bess_opt = n_gen.stores.loc[bess_store_id, "e_nom_opt"] - n_gen.stores.loc[bess_store_id, "e_nom"] if "e_nom" in n_gen.stores.columns and not pd.isna(n_gen.stores.loc[bess_store_id, "e_nom"]) else n_gen.stores.loc[bess_store_id, "e_nom_opt"]

    results["Scenario_B_Local_Generation"] = {
        "Target_Corridor/Node": target_node,
        "Total_Objective_Cost_EUR": n_gen.objective,
        "Line_Expansion_Added_MVA": 0.0,
        "Local_PV_Added_MW": max(0.0, pv_opt),
        "Local_BESS_Added_MWh": max(0.0, bess_opt)
    }

    # Compile comparative synthesis table
    comparison_df = pd.DataFrame(results).T
    min_cost = comparison_df["Total_Objective_Cost_EUR"].min()
    comparison_df["Cost_Delta_vs_Min_EUR"] = comparison_df["Total_Objective_Cost_EUR"] - min_cost
    
    return comparison_df

if __name__ == "__main__":
    df_comparison = run_comparative_expansion_study(
        base_network_path="results/base_s_adm__none_2030.nc"
    )
    print("\n==========================================================")
    print("      CO-OPTIMIZATION INVESTMENT DECISION MATRIX          ")
    print("==========================================================")
    print(df_comparison.to_string(formatters={
        "Total_Objective_Cost_EUR": "€{:,.2f}".format,
        "Line_Expansion_Added_MVA": "{:,.2f} MVA".format,
        "Local_PV_Added_MW": "{:,.2f} MW".format,
        "Local_BESS_Added_MWh": "{:,.2f} MWh".format,
        "Cost_Delta_vs_Min_EUR": "€{:,.2f}".format
    }))
    print("==========================================================\n")