# PyPSA-AT Analytics

Enterprise Streamlit dashboard + ETL + provenance tracking for solved PyPSA-AT
networks.

## Directory Structure

```
pypsa-at-analytics/
├── config/                          # Live config used for the NEXT PyPSA-AT run
│   ├── config.at.yaml
│   └── scenarios.manual.yaml
├── runs/                            # Provenance archive (see "Scenario Tracking" below)
│   └── <run_tag>/
│       ├── manifest.yaml            # created_at, git commit, notes, linked results/*.nc fingerprints
│       └── config/                  # snapshot copy of config/*.yaml at archive time
├── results/                         # Solved NetCDF network files (.nc) -- OVERWRITTEN each PyPSA-AT run
├── data/                            # Durable Parquet dashboard store (append-only across runs)
├── scripts/
│   ├── manifest_utils.py            # shared helpers (git commit, fingerprinting, manifest I/O)
│   ├── archive_run.py               # NEW: snapshot config + fingerprint results into runs/<tag>/
│   ├── diff_configs.py              # NEW: deep-diff two runs' config YAMLs -> changed-parameter table
│   ├── extract_runs.py              # UPDATED: run_tag-aware ETL, appends (not overwrites) Parquet store
│   ├── audit_baseline.py            # Baseline capacity share tables (per .nc file)
│   ├── analyze_corridor.py          # Line loading & congestion duration (per .nc file)
│   └── run_expansion_study.py       # Co-optimization scenario runner (Lines vs. Local Assets)
└── app.py                           # Streamlit interactive workbench (8 tabs, incl. new Report tab)
```

## Why the provenance layer exists

`results/*.nc` gets overwritten every time PyPSA-AT is re-run with a modified
config -- there is only ever one `results/base_s_adm__none_2030.nc` on disk at
a time. Without extra bookkeeping, once you overwrite it with a new scenario,
you lose the ability to compare "before" vs "after" and to say *which config
produced which numbers*.

This repo solves that **without ever copying or regenerating `.nc` files**:

1. **`scripts/archive_run.py --tag <name> --notes "..."`**
   Snapshots the current (small) `config/*.yaml` files into `runs/<tag>/config/`,
   and records a lightweight fingerprint (filename + byte size, optionally a
   SHA-256 hash) of every `results/*.nc` file present at that moment into
   `runs/<tag>/manifest.yaml`. This is your "checkpoint" -- run it right after
   a PyPSA-AT solve completes, before you touch the config again.

2. **`scripts/extract_runs.py`**
   Reads `results/*.nc`, matches each file back to the run that archived it
   (by filename + size), tags every extracted row with that `run_tag`, and
   **appends** the result into `data/*.parquet` (deduplicated by
   `run_tag` + `scenario`). Older runs already in the Parquet store are left
   untouched even after their `.nc` file is long gone from `results/`.

3. **`scripts/diff_configs.py --base <tag> --target <tag>`**
   Deep-diffs two archived runs' merged config YAMLs and prints/saves a flat
   table of exactly which parameters changed, old value vs. new value.

4. **`app.py` → Tab "Scenario Provenance & Report"**
   Lets you pick a baseline run and a target run, and shows:
   - the manifest overview (when, git commit, linked networks, your notes)
   - the automatic config diff table
   - the resulting KPI/dispatch deltas (cost, generation, PV/wind, grid
     losses, transmission capacity)
   - an auto-generated narrative paragraph tying the config change to the
     outcome
   - Excel/CSV export of the full comparison

## Typical Workflow

```bash
# 1. Run PyPSA-AT normally with config/config.at.yaml -> produces results/*.nc

# 2. Checkpoint this run BEFORE changing the config again
python scripts/archive_run.py --tag baseline_2025.04 \
    --notes "Initial AT_KN2040 baseline, AT split into 3 admin regions, H2 electrolysis min 1 GW."

# 3. Extract into the durable Parquet store
python scripts/extract_runs.py

# 4. Modify config/config.at.yaml (e.g. raise H2 electrolysis capacity, change clustering)
#    Re-run PyPSA-AT -> results/*.nc is overwritten with the new scenario's networks

# 5. Checkpoint the new run
python scripts/archive_run.py --tag high_h2_electrolysis \
    --notes "Raised AT H2 Electrolysis min capacity to 2 GW; AT clustering to 5 regions."

# 6. Extract again -- both runs now coexist in data/*.parquet
python scripts/extract_runs.py

# 7. (optional, CLI) Inspect the config diff directly
python scripts/diff_configs.py --base baseline_2025.04 --target high_h2_electrolysis

# 8. Launch the dashboard and open "Scenario Provenance & Report"
streamlit run app.py
```

## Notes

- `run_tag` values also disambiguate the scenario dropdown across the whole
  dashboard once more than one run has been extracted (scenario names are
  shown as `<scenario>  [<run_tag>]`), so Tabs 1-6 automatically stay
  consistent with the new provenance model without any manual remapping.
- If you extract without ever archiving a run first, rows are tagged
  `unarchived` so nothing breaks -- but you lose config traceability for that
  batch, so it's best to always `archive_run.py` right after a solve.
- `--reset` on `extract_runs.py` wipes and rebuilds the Parquet store from
  only what's currently in `results/`, useful if the history gets messy
  during testing.
