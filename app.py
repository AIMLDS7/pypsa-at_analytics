import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import io

# Configure minimalist enterprise design system
st.set_page_config(page_title="PyPSA-AT Mission Control Workbench", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background-color: #F8F9FA; border: 1px solid #E9ECEF; padding: 0.8rem; border-radius: 6px;
    }
    h1, h2, h3 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-weight: 500; }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# NOMENCLATURE & CARRIER MAPPINGS
# =========================================================
NUTS_MAP = {
    "AT11": "Burgenland", "AT12": "Lower Austria", "AT13": "Vienna",
    "AT21": "Carinthia", "AT22": "Styria", "AT31": "Upper Austria (Linz/Wels)",
    "AT32": "Salzburg", "AT33": "Tyrol", "AT34": "Vorarlberg",
    "DE1": "Germany (South/West)", "DE2": "Germany (South/East)", "DE3": "Germany (North/West)",
    "DE4": "Germany (East)", "DE5": "Germany (Central)", "CZ": "Czech Republic", "SK": "Slovakia"
}

TECHNICAL_GLOSSARY = {
    "LMP (Locational Marginal Price)": "The dual/shadow price of power balance at a specific substation node (€/MWh). Reflects the marginal cost to serve 1 additional MWh of demand at that location under network constraints.",
    "S_nom (Nominal Capacity)": "The maximum continuous apparent power thermal rating of an AC transmission branch or transformer, measured in MVA.",
    "P_nom (Installed Capacity)": "The maximum active power generation capability of a physical power plant or storage asset, measured in MW.",
    "Slack / Penalty Price Spikes": "Artificial solver price ceilings (often > €1,000/MWh) automatically triggered when unserved energy or dummy generators activate to prevent mathematical model infeasibility.",
    "N-1 Security Threshold": "Operating grid corridors below 90% thermal capacity to maintain a structural safety buffer against unexpected single-component outages.",
    "Monotonic Duration Curve": "A time-series distribution where all 8,760 annual hours are sorted descending by intensity, allowing immediate visualization of peaking hours vs. base-load conditions."
}

def map_macro_carrier(carrier: str) -> str:
    c_lower = str(carrier).lower()
    if any(k in c_lower for k in ["solar"]): return "Solar PV (All Types)"
    if any(k in c_lower for k in ["wind"]): return "Wind Power (Onshore & Offshore)"
    if any(k in c_lower for k in ["biomass", "biogas", "bioliquid", "waste"]): return "Bioenergy & Waste"
    if any(k in c_lower for k in ["gas", "coal", "lignite", "oil", "uranium"]): return "Thermal Fossil & Gas"
    if any(k in c_lower for k in ["ror", "hydro", "battery", "storage"]): return "Hydro & Storage"
    return "Heat, Synthetic Fuels & Other"

def decode_nuts(bus_id: str) -> str:
    for prefix, region in NUTS_MAP.items():
        if str(bus_id).startswith(prefix):
            return f"{bus_id} ({region})"
    return str(bus_id)

@st.cache_data
def load_data():
    kpi = pd.read_parquet("data/kpi_summary.parquet").sort_values("scenario")
    try: fleet = pd.read_parquet("data/fleet_summary.parquet")
    except FileNotFoundError: fleet = pd.DataFrame()
    dispatch = pd.read_parquet("data/hourly_dispatch.parquet")
    try: lines = pd.read_parquet("data/lines_summary.parquet")
    except FileNotFoundError: lines = pd.DataFrame()
    try: buses = pd.read_parquet("data/buses_summary.parquet")
    except FileNotFoundError: buses = pd.DataFrame()
    try: soc = pd.read_parquet("data/bess_soc.parquet")
    except FileNotFoundError: soc = pd.DataFrame()
    try: prices = pd.read_parquet("data/hourly_prices.parquet")
    except FileNotFoundError: prices = pd.DataFrame()
    return kpi, fleet, dispatch, lines, buses, soc, prices

def to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='PyPSA_Export')
    return output.getvalue()

kpi_df, fleet_df, dispatch_df, lines_df, buses_df, soc_df, prices_df = load_data()

# Header
st.title("PyPSA-AT Spatial Co-Optimization Mission Control")
st.markdown("Enterprise power systems observability with 2-tier carrier grouping and master filter overrides.")

# Global Sidebar Controls
with st.sidebar:
    st.header("Global Scenario Filter")
    all_scenarios = kpi_df["scenario"].unique().tolist()
    selected_scenarios = st.multiselect("Active Horizons:", options=all_scenarios, default=all_scenarios)
    
    st.divider()
    st.header("View Mode Toggle")
    view_mode = st.radio(
        "Carrier Granularity Level:",
        options=["🟢 Macro Aggregated Groups (6 Buckets)", "⚪ Granular Raw Carriers (25+ Items)"]
    )
    is_macro = "Macro" in view_mode

if not selected_scenarios:
    st.info("Please select at least one scenario from the sidebar.")
    st.stop()

# Filter active scenario data
kpi_sub = kpi_df[kpi_df["scenario"].isin(selected_scenarios)]
fleet_sub = fleet_df[fleet_df["scenario"].isin(selected_scenarios)] if not fleet_df.empty else pd.DataFrame()
dispatch_sub = dispatch_df[dispatch_df["scenario"].isin(selected_scenarios)]
lines_sub = lines_df[lines_df["scenario"].isin(selected_scenarios)] if not lines_df.empty else pd.DataFrame()
buses_sub = buses_df[buses_df["scenario"].isin(selected_scenarios)] if not buses_df.empty else pd.DataFrame()
soc_sub = soc_df[soc_df["scenario"].isin(selected_scenarios)] if not soc_df.empty else pd.DataFrame()
prices_sub = prices_df[prices_df["scenario"].isin(selected_scenarios)] if not prices_df.empty else pd.DataFrame()

# Apply Macro Carrier Grouping if Toggled
if is_macro:
    if not fleet_sub.empty:
        fleet_sub["display_carrier"] = fleet_sub["carrier"].apply(map_macro_carrier)
        fleet_sub = fleet_sub.groupby(["scenario", "display_carrier"])["installed_p_nom_mw"].sum().reset_index()
    dispatch_sub["display_carrier"] = dispatch_sub["carrier"].apply(map_macro_carrier)
    dispatch_sub = dispatch_sub.groupby(["scenario", "snapshot", "display_carrier"])["dispatch_mw"].sum().reset_index()
else:
    if not fleet_sub.empty:
        fleet_sub["display_carrier"] = fleet_sub["carrier"]
    dispatch_sub["display_carrier"] = dispatch_sub["carrier"]

# =========================================================
# 7-TAB MISSION CONTROL CENTER
# =========================================================
tab_fleet, tab_dispatch, tab_delta, tab_corridor, tab_nodal, tab_bess, tab_glossary = st.tabs([
    "1. Infrastructure Fleet ($P_{nom}$ / $S_{nom}$)",
    "2. Chronological Dispatch Stack",
   r"3. Scenario Delta Engine ($\Delta$)",
    "4. Transmission Corridor Audit",
    "5. Smart Nodal Market Explorer",
    "6. BESS State of Charge ($E_t$)",
    "7. Nomenclature Reference"
])

# ---------------------------------------------------------
# TAB 1: INFRASTRUCTURE FLEET ($P_{nom}$ / $S_{nom}$)
# ---------------------------------------------------------
with tab_fleet:
    st.subheader("Baseline Infrastructure Fleet ($P_{nom}$ Generation & $S_{nom}$ Transmission)")
    st.markdown("Installed asset inventory reflecting physical power plant construction and grid transfer capability.")
    
    t_cols = st.columns(len(selected_scenarios))
    for idx, row in kpi_sub.iterrows():
        with t_cols[selected_scenarios.index(row["scenario"])]:
            display_name = row['scenario'].split('_')[-1] if '_' in row['scenario'] else row['scenario']
            st.markdown(f"**Horizon: {display_name}**")
            st.metric("Total System Cost", f"€{row['total_system_cost_eur']/1e9:.2f} B")
            st.metric("AC Line Backbone ($S_{nom}$)", f"{row.get('total_ac_line_capacity_mva', 0.0)/1e3:,.1f} GVA")
            st.metric("Grid Loss Margin", f"{row.get('grid_loss_pct', 0.0):.2f}%", delta=f"{row.get('solver_status', 'Optimal')}", delta_color="normal")

    st.divider()
    if not fleet_sub.empty:
        fig_fleet = px.bar(
            fleet_sub, x="display_carrier", y="installed_p_nom_mw", color="scenario", barmode="group",
            template="plotly_white", title=f"Installed Generation Capacity Fleet ($P_{{nom}}$ in MW) [{view_mode}]",
            labels={"installed_p_nom_mw": "Installed Capacity (MW)", "display_carrier": "Energy Carrier Group"}
        )
        fig_fleet.update_layout(margin=dict(l=0, r=0, t=40, b=0), xaxis_tickangle=-30)
        st.plotly_chart(fig_fleet, use_container_width=True)
        
        e1, e2 = st.columns(2)
        e1.download_button("📊 Download Fleet Data (.xlsx)", to_excel(fleet_sub), "Fleet_Inventory.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        e2.download_button("📄 Download Fleet Data (.csv)", fleet_sub.to_csv(index=False).encode('utf-8'), "Fleet_Inventory.csv", "text/csv")
    else:
        st.warning("No installed capacity data available.")

# ---------------------------------------------------------
# TAB 2: CHRONOLOGICAL DISPATCH STACK
# ---------------------------------------------------------
with tab_dispatch:
    st.subheader(f"Hourly Operational Generation Profiles [{view_mode}]")
    view_scen = st.selectbox("Inspect Scenario Horizon:", options=selected_scenarios, key="disp_scen")
    fig_disp = px.area(
        dispatch_sub[dispatch_sub["scenario"] == view_scen], x="snapshot", y="dispatch_mw", color="display_carrier",
        template="plotly_white", labels={"dispatch_mw": "Dispatch (MW)", "snapshot": "Timestamp", "display_carrier": "Carrier"}
    )
    fig_disp.update_layout(margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified")
    st.plotly_chart(fig_disp, use_container_width=True)

# ---------------------------------------------------------
# TAB 3: SCENARIO DELTA ENGINE ($\Delta \text{Target} - \Delta \text{Base}$)
# ---------------------------------------------------------
with tab_delta:
    st.subheader(rf"Dynamic Scenario Delta Comparator ($\Delta \text{{Target}} - \Delta \text{{Base}}$) [{view_mode}]")
    st.markdown("Mathematically subtract a baseline transition year from a target scenario to isolate net capacity and generation shifts.")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        base_scen = st.selectbox("Select Baseline Horizon (Base):", options=selected_scenarios, index=0)
    with col_d2:
        target_scen = st.selectbox("Select Target Horizon (Target):", options=selected_scenarios, index=len(selected_scenarios)-1)
        
    base_row = kpi_sub[kpi_sub["scenario"] == base_scen].iloc[0]
    target_row = kpi_sub[kpi_sub["scenario"] == target_scen].iloc[0]
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Δ System Cost", f"€{(target_row['total_system_cost_eur'] - base_row['total_system_cost_eur'])/1e9:+.2f} B", delta=f"vs {base_scen}")
    m2.metric("Δ Annual Generation", f"{(target_row['total_generation_mwh'] - base_row['total_generation_mwh'])/1e6:+.2f} TWh")
    m3.metric("Δ Solar PV Share", f"{(target_row['pv_mwh'] - base_row['pv_mwh'])/1e6:+.2f} TWh")
    
    disp_base = dispatch_sub[dispatch_sub["scenario"] == base_scen].groupby("display_carrier")["dispatch_mw"].sum()
    disp_target = dispatch_sub[dispatch_sub["scenario"] == target_scen].groupby("display_carrier")["dispatch_mw"].sum()
    delta_df = pd.DataFrame({"Base (MWh)": disp_base, "Target (MWh)": disp_target}).fillna(0.0)
    delta_df["Delta (TWh)"] = (delta_df["Target (MWh)"] - delta_df["Base (MWh)"]) / 1e6
    
    fig_delta = px.bar(
        delta_df.reset_index(), x="display_carrier", y="Delta (TWh)", color="Delta (TWh)",
        color_continuous_scale="RdBu", title=f"Net Generation Shift: {target_scen} minus {base_scen}",
        template="plotly_white", labels={"display_carrier": "Energy Carrier", "Delta (TWh)": "Net Shift (TWh)"}
    )
    st.plotly_chart(fig_delta, use_container_width=True)
    st.dataframe(delta_df.style.format("{:,.2f}"), use_container_width=True)

# ---------------------------------------------------------
# TAB 4: TRANSMISSION CORRIDOR AUDIT (With Show-All Override)
# ---------------------------------------------------------
with tab_corridor:
    st.subheader("System-Wide Transmission Corridor Audit")
    if not lines_sub.empty:
        col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
        with col_c1:
            show_all_lines = st.checkbox("🌐 Show All Transmission Lines (Bypass Utilization Filter)", value=False)
        with col_c2:
            min_util = 0.0 if show_all_lines else st.slider("Minimum Peak Utilization (%)", 0.0, 100.0, 50.0, 5.0, disabled=show_all_lines)
        with col_c3:
            bus_search = st.text_input("Filter by Substation ID:", placeholder="e.g., DE3, AT0, CZ")
            
        lines_f = lines_sub if show_all_lines else lines_sub[lines_sub["Peak_Utilization_Pct"] >= min_util]
        if bus_search:
            lines_f = lines_f[lines_f["Bus_0"].str.contains(bus_search, case=False) | lines_f["Bus_1"].str.contains(bus_search, case=False)]
            
        st.markdown(f"**Displaying `{len(lines_f):,}` transmission corridors:**")
        fig_lines = px.bar(
            lines_f.head(25), x="Line_ID", y="Peak_Utilization_Pct", color="scenario", barmode="group",
            template="plotly_white", title="Side-by-Side Peak Corridor Utilization Comparison"
        )
        fig_lines.add_hline(y=90.0, line_dash="dash", line_color="red", annotation_text="90% N-1 Safety Limit")
        st.plotly_chart(fig_lines, use_container_width=True)
        
        st.markdown("### 📥 Structured Data Export")
        el1, el2 = st.columns(2)
        el1.download_button("📊 Download Corridors (.xlsx)", to_excel(lines_f), "Transmission_Corridors.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        el2.download_button("📄 Download Corridors (.csv)", lines_f.to_csv(index=False).encode('utf-8'), "Transmission_Corridors.csv", "text/csv")
        st.dataframe(lines_f.sort_values(["Peak_Utilization_Pct"], ascending=False), use_container_width=True)
    else:
        st.warning("No line data available.")

# ---------------------------------------------------------
# TAB 5: SMART NODAL MARKET EXPLORER (With Master Overrides)
# ---------------------------------------------------------
with tab_nodal:
    st.subheader("Smart Nodal Price (LMP) Diagnostics & Master Filter Overrides")
    if not buses_sub.empty:
        buses_sub["Carrier_Type"] = buses_sub["Bus_ID"].apply(
            lambda x: "Electrical AC Grid" if len(str(x)) <= 6 and ("AT" in str(x) or "DE" in str(x)) else (
                "Synthetic Methanol" if "methanol" in str(x) else (
                "Hydrogen (H2)" if "H2" in str(x) else (
                "District Heating" if "heat" in str(x) else "Battery / Storage / Other"))
            )
        )
        buses_sub["Decoded_Region"] = buses_sub["Bus_ID"].apply(decode_nuts)

        col_o1, col_o2 = st.columns(2)
        with col_o1:
            show_all_carriers = st.checkbox("🌐 Inspect All Energy Carriers (Unfiltered EDA Mode)", value=False)
        with col_o2:
            disable_price_ceiling = st.checkbox("⚠️ Disable Price Ceiling (Show Raw Solver Penalty Slacks)", value=False)

        col_f1, col_f2, col_f3 = st.columns([1, 1, 1])
        with col_f1:
            carriers = buses_sub["Carrier_Type"].unique().tolist()
            default_c = ["Electrical AC Grid"] if "Electrical AC Grid" in carriers else carriers
            sel_carrier = carriers if show_all_carriers else st.multiselect("1. Energy Carrier Subsets:", options=carriers, default=default_c, disabled=show_all_carriers)
        with col_f2:
            max_cap = np.inf if disable_price_ceiling else st.number_input("2. Price Ceiling Filter (€/MWh):", value=600.0, step=100.0, disabled=disable_price_ceiling)
        with col_f3:
            reg_filter = st.text_input("3. Filter NUTS Region:", placeholder="Leave blank for all regions")

        buses_clean = buses_sub[buses_sub["Carrier_Type"].isin(sel_carrier)]
        buses_clean = buses_clean[buses_clean["Mean_LMP_EUR_MWh"] <= max_cap]
        if reg_filter:
            buses_clean = buses_clean[buses_clean["Decoded_Region"].str.contains(reg_filter, case=False)]

        st.markdown(f"**Displaying `{len(buses_clean):,}` nodes matching filter criteria:**")
        top_nodes = buses_clean.groupby("Decoded_Region")["Mean_LMP_EUR_MWh"].mean().nlargest(20).index
        chart_data = buses_clean[buses_clean["Decoded_Region"].isin(top_nodes)]

        fig_lmp = px.bar(
            chart_data, x="Decoded_Region", y="Mean_LMP_EUR_MWh", color="scenario", barmode="group",
            error_y="Price_Volatility_Std",
            title="Nodal Marginal Prices with Volatility Dispersion (Standard Deviation Error Bars)",
            template="plotly_white", labels={"Mean_LMP_EUR_MWh": "Mean Annual LMP (€/MWh)", "Decoded_Region": "Geographic Node"}
        )
        fig_lmp.update_layout(margin=dict(l=0, r=0, t=40, b=0), xaxis_tickangle=-45)
        st.plotly_chart(fig_lmp, use_container_width=True)

        st.markdown("### 📥 Export Cleaned Nodal Market Data")
        en1, en2 = st.columns(2)
        en1.download_button("📊 Download Nodal LMPs (.xlsx)", to_excel(buses_clean), "Cleaned_Nodal_LMPs.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        en2.download_button("📄 Download Nodal LMPs (.csv)", buses_clean.to_csv(index=False).encode('utf-8'), "Cleaned_Nodal_LMPs.csv", "text/csv")
        st.dataframe(buses_clean[["scenario", "Decoded_Region", "Carrier_Type", "Mean_LMP_EUR_MWh", "Max_LMP_EUR_MWh", "Price_Volatility_Std"]].sort_values("Mean_LMP_EUR_MWh", ascending=False), use_container_width=True)
    else:
        st.warning("No nodal data available.")

# ---------------------------------------------------------
# TAB 6: BESS STATE OF CHARGE ($E_t$) & DURATION CURVES
# ---------------------------------------------------------
with tab_bess:
    st.subheader("Battery State of Charge Tracking ($E_t$) & Monotonic Duration Curves")
    sub_soc, sub_pdc = st.tabs(["Continuous Battery Trajectories ($E_t$)", "Monotonic Price Duration Curves (PDCs)"])
    
    with sub_soc:
        if not soc_sub.empty:
            fig_soc = px.line(
                soc_sub, x="snapshot", y="state_of_charge_mwh", color="scenario",
                title="System-Wide Battery State of Charge Profile ($E_t$ in MWh)",
                template="plotly_white", labels={"state_of_charge_mwh": "Stored Energy (MWh)", "snapshot": "Timeline"}
            )
            fig_soc.update_layout(margin=dict(l=0, r=0, t=30, b=0), hovermode="x unified")
            st.plotly_chart(fig_soc, use_container_width=True)
            
            eb1, eb2 = st.columns(2)
            eb1.download_button("📊 Download SoC Data (.xlsx)", to_excel(soc_sub), "BESS_SoC.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            eb2.download_button("📄 Download SoC Data (.csv)", soc_sub.to_csv(index=False).encode('utf-8'), "BESS_SoC.csv", "text/csv")
        else:
            st.info("No active storage units detected.")
            
    with sub_pdc:
        if not prices_sub.empty:
            st.markdown("Sorting all 8,760 hourly snapshots descending illustrates structural grid stress duration independent of chronological noise.")
            fig_pdc = go.Figure()
            for scen in selected_scenarios:
                sorted_p = prices_sub[prices_sub["scenario"] == scen]["mean_electrical_lmp_eur_mwh"].sort_values(ascending=False).values
                display_name = scen.split('_')[-1] if '_' in scen else scen
                fig_pdc.add_trace(go.Scatter(y=sorted_p, mode="lines", name=display_name))
            fig_pdc.update_layout(
                title="Monotonic Electrical Price Duration Curve (Sorted by Grid Stress)",
                template="plotly_white", xaxis_title="Duration (Hours Sorted Descending)", yaxis_title="Mean Electrical LMP (€/MWh)",
                margin=dict(l=0, r=0, t=40, b=0), hovermode="x unified"
            )
            st.plotly_chart(fig_pdc, use_container_width=True)
        else:
            st.info("No time-series price data extracted.")

# ---------------------------------------------------------
# TAB 7: NOMENCLATURE REFERENCE
# ---------------------------------------------------------
with tab_glossary:
    st.subheader("Engineering Nomenclature & Telemetry Glossary")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("### 🌍 NUTS Regional Mapping")
        st.table(pd.DataFrame(list(NUTS_MAP.items()), columns=["Grid Code Prefix", "Administrative Region"]))
    with g2:
        st.markdown("### ⚡ Telemetry Definitions")
        for term, desc in TECHNICAL_GLOSSARY.items():
            st.markdown(f"**{term}**")
            st.markdown(f"*{desc}*")
            st.divider()