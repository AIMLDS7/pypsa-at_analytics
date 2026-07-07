import pypsa
import pandas as pd

def analyze_transmission_corridor(n: pypsa.Network, bus_source: str, bus_sink: str, threshold_pct: float = 90.0) -> pd.DataFrame:
    """
    Isolates lines connecting two buses and computes post-optimization loading metrics.
    Ensures generic systems evaluation regardless of spatial orientation.
    """
    # Identify connecting branches bidirectional (bus0 -> bus1 OR bus1 -> bus0)
    mask = ((n.lines["bus0"] == bus_source) & (n.lines["bus1"] == bus_sink)) | \
           ((n.lines["bus0"] == bus_sink) & (n.lines["bus1"] == bus_source))
    
    corridor_lines = n.lines[mask]
    if corridor_lines.empty:
        raise ValueError(f"No direct AC line branch identified between '{bus_source}' and '{bus_sink}'.")
    
    metrics = []
    for line_id, row in corridor_lines.iterrows():
        # Retrieve hourly absolute flow time-series
        hourly_flow_mw = n.lines_t.p0[line_id].abs()
        s_nom = row["s_nom"]
        
        hourly_utilization = (hourly_flow_mw / s_nom) * 100
        congested_hours = (hourly_utilization >= threshold_pct).sum()
        
        metrics.append({
            "Line_ID": line_id,
            "Bus_0": row["bus0"],
            "Bus_1": row["bus1"],
            "Voltage_kV": row["v_nom"],
            "Length_km": row["length"],
            "Nominal_Capacity_MVA": s_nom,
            "Max_Observed_Flow_MW": hourly_flow_mw.max(),
            "Peak_Utilization_Pct": hourly_utilization.max(),
            "Mean_Utilization_Pct": hourly_utilization.mean(),
            "Congested_Hours": congested_hours,
            "Congestion_Duration_Pct": (congested_hours / len(n.snapshots)) * 100
        })
        
    return pd.DataFrame(metrics)

if __name__ == "__main__":
    network_path = "results/base_s_adm__none_2030.nc"
    print(f"Loading network: {network_path}...")
    n = pypsa.Network(network_path)
    
    # Target bus IDs to evaluate
    source_bus = "bus_A"
    sink_bus = "bus_B"
    
    # Auto-detect valid connected buses if placeholder strings are detected
    if source_bus not in n.buses.index or sink_bus not in n.buses.index:
        # Sort lines by voltage and capacity to evaluate a primary transmission corridor
        high_voltage_lines = n.lines[n.lines["v_nom"] >= 110].sort_values(by="s_nom", ascending=False)
        selected_line = high_voltage_lines.iloc[0] if not high_voltage_lines.empty else n.lines.iloc[0]
        
        source_bus = selected_line["bus0"]
        sink_bus = selected_line["bus1"]
        print(f"[Auto-Detect] Placeholder IDs detected. Analyzing primary grid corridor between '{source_bus}' and '{sink_bus}'...")
    
    df_corridor = analyze_transmission_corridor(n, bus_source=source_bus, bus_sink=sink_bus)
    
    print("\n==========================================================================================")
    print("                              TRANSMISSION CORRIDOR AUDIT                                 ")
    print("==========================================================================================")
    print(df_corridor.to_string(index=False, formatters={
        "Nominal_Capacity_MVA": "{:,.2f}".format,
        "Max_Observed_Flow_MW": "{:,.2f}".format,
        "Peak_Utilization_Pct": "{:.2f}%".format,
        "Mean_Utilization_Pct": "{:.2f}%".format,
        "Congestion_Duration_Pct": "{:.2f}%".format
    }))
    print("==========================================================================================\n")
    
    df_corridor.to_csv("data/corridor_loading_analysis.csv", index=False)
    print("Results saved successfully to 'data/corridor_loading_analysis.csv'.")