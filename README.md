<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0f2027,50:203a43,100:2c5364&height=200&section=header&text=⚡%20PyPSA-AT%20Analytics&fontSize=38&fontColor=ffffff&fontAlignY=38&desc=Provenance-Tracked%20ETL%20%2B%20Streamlit%20Dashboard%20for%20Macro-Energy%20Simulations&descAlignY=60&descSize=15" width="100%"/>


[![Open in GitHub](https://img.shields.io/badge/View_on-GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/AIMLDS7/pypsa-at-analytics)

<div align="center">

**Built with:**

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PyPSA](https://img.shields.io/badge/PyPSA-Energy%20Modeling-1E88E5?style=flat-square)](https://pypsa.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Pandas](https://img.shields.io/badge/Pandas-150458?style=flat-square&logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![Apache Parquet](https://img.shields.io/badge/Apache_Parquet-50ABF1?style=flat-square&logo=apacheparquet&logoColor=white)](https://parquet.apache.org/)
[![YAML](https://img.shields.io/badge/Config-YAML-CB171E?style=flat-square&logo=yaml&logoColor=white)](https://yaml.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)

</div>

**Provenance-first energy analytics** — every solved PyPSA-AT network is fingerprinted, checkpointed, and appended to a durable Parquet store, so overwriting `results/*.nc` never means losing the ability to compare scenarios.

[🏗 Architecture](#-architecture) · [📊 Dashboard](#-dashboard) · [🚀 Quick Start](#-quick-start)

</div>

<div align="center">

[![Stars](https://img.shields.io/github/stars/AIMLDS7/pypsa-at-analytics?style=social)](https://github.com/AIMLDS7/pypsa-at-analytics/stargazers)
[![Forks](https://img.shields.io/github/forks/AIMLDS7/pypsa-at-analytics?style=social)](https://github.com/AIMLDS7/pypsa-at-analytics/network/members)
[![Last commit](https://img.shields.io/github/last-commit/AIMLDS7/pypsa-at-analytics)](https://github.com/AIMLDS7/pypsa-at-analytics/commits)

</div>

---

## Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Pipeline Components](#-pipeline-components)
- [Manifest & Store Schema](#-manifest--store-schema)
- [Dashboard](#-dashboard)
- [Quick Start](#-quick-start)
- [Repository Structure](#-repository-structure)
- [Technical Decisions](#️-technical-decisions)
- [Changelog](#-changelog)
- [Limitations & Future Work](#️-limitations--future-work)
- [Dependencies](#-dependencies)

---

## 🔭 Overview

Large-scale PyPSA-AT runs solve into `results/*.nc` — and every re-run with a modified config **overwrites** those files. There is only ever *one* `results/base_s_adm__none_2030.nc` on disk at a time. Without extra bookkeeping, once you overwrite it you lose the ability to say *which config produced which numbers*.

This platform solves that **without ever copying or regenerating `.nc` files**, by splitting the problem into two independent, composable layers:

| Concern | Handled by | Persists to |
|---|---|---|
| 🧬 **Provenance** — which config produced this run? | `archive_run.py` | `runs/<run_tag>/manifest.yaml` |
| 📊 **Analytics** — what do the numbers say across runs? | `extract_runs.py` | `data/*.parquet` |
| 🔀 **Regression** — what changed between two runs? | `diff_configs.py` | printed table / CSV |

**At a glance:** 3 provenance scripts · append-only Parquet lake · 8-tab Streamlit workbench · zero `.nc` duplication.

**Why keep them separate?**

| Scenario | What you'd reach for |
|---|---|
| Just solved a run, about to change the config | `archive_run.py --tag <name>` — checkpoint *now* |
| Want cross-scenario KPI comparisons in the dashboard | `extract_runs.py` — ingest into Parquet |
| Need to know exactly which parameters changed | `diff_configs.py --base <a> --target <b>` |

---

## 🏗 Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        SYSTEM DATA FLOW                                  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐                                                      │
│   │ PyPSA-AT     │                                                      │
│   │ solve        │                                                      │
│   └──────┬───────┘                                                      │
│          │ writes / overwrites                                         │
│          ▼                                                              │
│   ┌──────────────┐                                                      │
│   │ results/*.nc │ ← ephemeral, single copy on disk                    │
│   └──────┬───────┘                                                      │
│          │                                                              │
│   ┌──────┴───────────────────────────┐                                  │
│   ▼                                  ▼                                  │
│ ┌────────────────────┐      ┌─────────────────────┐                     │
│ │ archive_run.py      │      │ extract_runs.py      │                     │
│ │ - snapshot config/  │      │ - read results/*.nc  │                     │
│ │ - fingerprint .nc   │      │ - match by filename  │                     │
│ │ - record git commit │      │   + size to run_tag  │                     │
│ └──────────┬──────────┘      └──────────┬──────────┘                     │
│            │                             │                               │
│            ▼                             ▼                               │
│ ┌─────────────────────┐       ┌──────────────────────┐                   │
│ │ runs/<run_tag>/      │──────▶│ data/*.parquet        │                  │
│ │  manifest.yaml       │ match │ append, dedup by      │                  │
│ │  config/*.yaml       │       │ run_tag + scenario    │                  │
│ └─────────────────────┘       └──────────┬───────────┘                   │
│                                            │                              │
│                                            ▼                              │
│                              ┌──────────────────────────┐                 │
│                              │  app.py — Streamlit       │                 │
│                              │  8-tab workbench           │                 │
│                              └──────────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Pipeline Components

### Component 1 — Provenance Engine (`archive_run.py`)

Run this **immediately after a solve completes**, before touching the config again. It snapshots the current `config/*.yaml` into `runs/<tag>/config/` and fingerprints every `results/*.nc` present at that moment.

```bash
python scripts/archive_run.py \
    --tag baseline_2025.04 \
    --notes "Initial AT_KN2040 baseline, AT split into 3 admin regions, H2 electrolysis min 1 GW."
```

> Fingerprint = filename + byte size, optionally a SHA-256 hash. This is your checkpoint — it's what lets `extract_runs.py` later prove which config produced a given `.nc`.

---

### Component 2 — ETL Engine (`extract_runs.py`)

Reads `results/*.nc`, matches each file back to the run that archived it, tags every extracted row with that `run_tag`, and **appends** into the Parquet store — it never overwrites.

```bash
python scripts/extract_runs.py
```

```
results/*.nc ──▶ matched to run_tag ──▶ appended ──▶ data/*.parquet
                                          (dedup on run_tag + scenario)
```

> Older runs already in the Parquet store stay untouched even after their `.nc` file is long gone from `results/`.

---

### Component 3 — Regression Engine (`diff_configs.py`)

Deep-diffs two archived runs' merged config YAMLs into a flat, old-value-vs-new-value table.

```bash
python scripts/diff_configs.py --base baseline_2025.04 --target high_h2_electrolysis
```

---

## 📋 Manifest & Store Schema

```
┌────────────────────┬──────────────────────────────────────────────────────┐
│ Field               │ Description                                          │
├────────────────────┼──────────────────────────────────────────────────────┤
│ run_tag             │ Human-chosen identifier, e.g. "baseline_2025.04"      │
│ created_at          │ ISO timestamp of the archive_run.py call              │
│ git_commit          │ SHA of the code state that produced the run           │
│ notes               │ Free-text description supplied via --notes           │
│ nc_fingerprints[]   │ filename + byte size (+ optional SHA-256) per .nc     │
│ config_snapshot     │ Point-in-time copy of config/*.yaml                   │
└────────────────────┴──────────────────────────────────────────────────────┘
```

**Parquet row key:** composite primary key of `run_tag + scenario` — re-running the ETL is idempotent; matching rows are silently upserted rather than duplicated.

---

## 📊 Dashboard

The **Scenario Provenance & Report** tab in `app.py` ties everything together:

| Panel | Shows |
|---|---|
| 🗂️ Manifest overview | When, git commit, linked networks, your notes |
| 🔀 Config diff table | Every parameter delta, old value vs. new value |
| 📈 KPI / dispatch deltas | Cost, generation, PV/wind, grid losses, transmission capacity |
| 📝 Narrative summary | Auto-generated paragraph tying the config change to the outcome |
| 📤 Export | Excel/CSV of the full comparison |

**Illustrative example** (numbers are placeholders — your dashboard will populate real deltas):

| KPI | `baseline_2025.04` | `high_h2_electrolysis` | Δ |
|---|---|---|---|
| System OPEX | €1.42 bn | €1.38 bn | **−2.8%** ✅ |
| CAPEX | €3.10 bn | €3.46 bn | +11.6% |
| Grid losses | 4.1% | 3.9% | −0.2 pp |
| Curtailment | 6.7% | 5.9% | −0.8 pp |

> Once more than one run has been extracted, scenario names appear as `<scenario> [<run_tag>]` throughout the dashboard, so every tab stays disambiguated automatically.

---

## 🚀 Quick Start

### 1 — Clone

```bash
git clone https://github.com/AIMLDS7/pypsa-at-analytics.git
cd pypsa-at-analytics
```

### 2 — Install dependencies

```bash
pip install streamlit>=1.30 pandas>=2.0 pyarrow>=14.0 pyyaml>=6.0 \
            gitpython>=3.1 deepdiff>=6.7 xlsxwriter>=3.1
```

### 3 — Run the pipeline

```bash
# a) Solve PyPSA-AT normally -> produces results/*.nc

# b) Checkpoint before touching the config again
python scripts/archive_run.py --tag baseline_2025.04 \
    --notes "Initial AT_KN2040 baseline."

# c) Ingest into the Parquet store
python scripts/extract_runs.py

# d) Change config/config.at.yaml, re-solve, checkpoint again with a new --tag,
#    then extract again — both runs now coexist in data/*.parquet
```

### 4 — Launch the dashboard

```bash
streamlit run app.py
```

Then open **Scenario Provenance & Report**.

<details>
<summary>🪟 <b>PowerShell equivalents</b> (Windows)</summary>

```powershell
python scripts/archive_run.py `
    --tag "baseline_2025.04" `
    --notes "Initial AT_KN2040 baseline, AT split into 3 admin regions."

python scripts/extract_runs.py

python scripts/diff_configs.py --base "baseline_2025.04" --target "high_h2_electrolysis"
```

> Make sure your PowerShell execution policy allows script execution if wrapping these in `.ps1` automation.

</details>

---

## 📁 Repository Structure

```
📦 pypsa-at-analytics/
│
├── ⚙️ config/                          ← Live config for the NEXT PyPSA-AT run
│   ├── config.at.yaml
│   └── scenarios.manual.yaml
│
├── 🗂 runs/                             ← Provenance archive
│   └── <run_tag>/
│       ├── manifest.yaml               ← created_at, git commit, notes, .nc fingerprints
│       └── config/                     ← snapshot copy of config/*.yaml at archive time
│
├── 📉 results/                          ← Solved NetCDF networks (.nc) — OVERWRITTEN each run
├── 📊 data/                             ← Durable Parquet dashboard store (append-only)
│
├── 🐍 scripts/
│   ├── manifest_utils.py               ← shared helpers (git commit, fingerprinting, manifest I/O)
│   ├── archive_run.py                  ← snapshot config + fingerprint results into runs/<tag>/
│   ├── diff_configs.py                 ← deep-diff two runs' config YAMLs
│   ├── extract_runs.py                 ← run_tag-aware ETL, appends to the Parquet store
│   ├── audit_baseline.py               ← baseline capacity share tables
│   ├── analyze_corridor.py             ← line loading & congestion duration
│   └── run_expansion_study.py          ← grid expansion co-optimization runner
│
├── 🖥 app.py                            ← Streamlit workbench (8 tabs, incl. Report tab)
├── 📄 README.md
└── 📄 LICENSE
```

---

## ⚙️ Technical Decisions

**Why fingerprint by filename + size instead of always hashing?**
Full SHA-256 hashing of multi-GB `.nc` files on every checkpoint is expensive. Filename + byte size is enough to reliably match a file back to the run that produced it in normal use; the optional SHA-256 is there for when you need cryptographic certainty.

**Why append-only Parquet instead of overwriting the store?**
`results/*.nc` is already ephemeral — one copy at a time. If the analytics store followed the same pattern, every new run would erase the ability to compare against the previous one. Append-only, deduplicated by `run_tag + scenario`, means old runs stay queryable long after their source `.nc` is gone.

**Why `run_tag + scenario` as the composite key, not just `scenario`?**
Scenario names are often reused across experiments (e.g. `2030` appears in every run). Without `run_tag` in the key, a later run would silently overwrite an earlier one with the same scenario name instead of coexisting alongside it.

**Why tag ungoverned extracts as `unarchived` instead of failing?**
Forgetting to run `archive_run.py` before extracting shouldn't lose your data — it should just tell you, loudly, that this batch has no config lineage. Rows are ingested and clearly labeled rather than silently dropped or blocking the pipeline.

**Why offer `--reset` on `extract_runs.py`?**
During active development the Parquet store can accumulate stale test runs. `--reset` rebuilds it from scratch using only what's currently in `results/`, without needing to manually delete files.

---

## 📋 Changelog

### v2.0 — Provenance Layer
- Added `archive_run.py` — config snapshot + `.nc` fingerprinting into `runs/<tag>/`
- Added `diff_configs.py` — structural YAML deep-diff between two runs
- `extract_runs.py` upgraded to be `run_tag`-aware; **appends** instead of overwriting
- Added **Scenario Provenance & Report** tab to `app.py` (now 8 tabs total)
- Dropdown labels across all tabs now disambiguate via `<scenario> [<run_tag>]`
- Added `--reset` flag to `extract_runs.py` for clean re-syncs during development

### v1.0 — Initial Dashboard
- Streamlit workbench over a single-snapshot Parquet extraction of `results/*.nc`
- Baseline capacity share and corridor congestion analytics tabs

---

## ⚠️ Limitations & Future Work

**Current limitations:**

| Limitation | Impact |
|---|---|
| Fingerprint match relies on filename + size by default | Two different `.nc` files that happen to share both could theoretically collide — enable full SHA-256 for strict environments |
| No automatic trigger after a solve | `archive_run.py` must be run manually right after each solve, or lineage is lost for that batch |
| Single-machine Parquet store | Not yet partitioned/distributed for very large numbers of concurrent scenario runs |
| No built-in run cleanup policy | `runs/` grows unbounded; old manifests must be pruned manually |

**Planned improvements:**

- [ ] Git pre/post-solve hook to auto-invoke `archive_run.py`
- [ ] Optional partitioned Parquet layout (by year / scenario family)
- [ ] Manifest retention policy / archival to cold storage
- [ ] Richer narrative engine (LLM-assisted KPI-to-config explanations)
- [ ] CI check that fails if `extract_runs.py` is run without a matching manifest

---

## 📦 Dependencies

| Package | Role |
|---|---|
| `streamlit` | Dashboard UI |
| `pandas` | Data wrangling, KPI aggregation |
| `pyarrow` | Parquet read/write |
| `pyyaml` | Config & manifest I/O |
| `gitpython` | Git commit introspection for manifests |
| `deepdiff` | Structural YAML diffing in `diff_configs.py` |
| `xlsxwriter` | Excel export from the Report tab |

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:2c5364,50:203a43,100:0f2027&height=100&section=footer" width="100%"/>

**Built with ⚡ PyPSA · 🐼 Pandas · 📊 Streamlit · 🪶 Apache Parquet**

*Model faster. Track everything.*

[![GitHub](https://img.shields.io/badge/GitHub-your--org-181717?style=flat-square&logo=github)](https://github.com/AIMLDS7)

</div>
