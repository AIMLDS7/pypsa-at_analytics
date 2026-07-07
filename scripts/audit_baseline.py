import pypsa
import pandas as pd

def audit_baseline_infrastructure(network_path: str) -> None:
    """
    Extracts and audits baseline generation and transmission capacities from a PyPSA network.
    """
    n = pypsa.Network(network_path)
    
    # 1. Aggregate Generation Assets by Carrier
    gen_audit = n.generators.groupby("carrier")["p_nom"].sum().reset_index()
    gen_audit.columns = ["Carrier", "Installed_Capacity_MW"]
    gen_audit["Share_Pct"] = (gen_audit["Installed_Capacity_MW"] / gen_audit["Installed_Capacity_MW"].sum()) * 100
    gen_audit = gen_audit.sort_values(by="Installed_Capacity_MW", ascending=False)
    
    # 2. Aggregate Transmission Infrastructure (AC Lines >= 110 kV & Transformers)
    high_voltage_lines = n.lines[n.lines["v_nom"] >= 110]
    total_ac_line_capacity = high_voltage_lines["s_nom"].sum()
    total_transformer_capacity = n.transformers["s_nom"].sum()
    
    print("==========================================================")
    print("         PYPSA-AT BASELINE INFRASTRUCTURE AUDIT           ")
    print("==========================================================")
    print("\n--- GENERATION PORTFOLIO (MW) ---")
    print(gen_audit.to_string(index=False, formatters={
        "Installed_Capacity_MW": "{:,.2f}".format,
        "Share_Pct": "{:.2f}%".format
    }))
    
    print("\n--- TRANSMISSION CORRIDORS (MVA) ---")
    print(f"Total High-Voltage AC Line Capacity (>=110 kV): {total_ac_line_capacity:,.2f} MVA")
    print(f"Total Substation Transformer Capacity:          {total_transformer_capacity:,.2f} MVA")
    print("==========================================================\n")

if __name__ == "__main__":
    audit_baseline_infrastructure("results/base_s_adm__none_2025.nc")