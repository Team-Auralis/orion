# NECTAR Connectome Accounting

> Exact source → imported → excluded accounting for the NECTAR connectome data.
> Every number computed directly from the files on disk (September 14, 2026).

## Source

- **FlyWire FAFB whole-brain connectome** (Dorkenwald et al., 2024; FlyWire resource). Nature describes the complete resource as **~140k neurons and >54.5M synapses**.
- **PhilShiu snapshot** (Shiu et al., *Nature* 634, 210-219, 2024, "A Drosophila computational brain model reveals sensorimotor processing"): the computational materialization shipped in the paper's `model.py`/`utils.py` repository. This is what NECTAR imports (v783 and v630 pre-annotation snapshots).

## v783 (`Completeness_783.csv` + `Connectivity_783.parquet`)

### Neurons

| Stage | Count | Notes |
|---|---|---|
| FlyWire complete resource | ~140k | approximate, per Nature network-statistics paper |
| Source roster (Completeness_783) | **138,639** | materialized neuron list, index = FlyWire root IDs |
| Unique neuron IDs in connectivity | **138,639** (pre 138,005 ∪ post 137,090) | every connection ID present in roster |
| Imported into NECTAR | **138,639** (100%) | all roster rows become Brian2 neurons |
| Excluded | **0** | no ID filtering; roster is the universe |
| Not-in-roster connection IDs | **0** | full internal consistency check passed |

### Synapses / edges

| Stage | Count | Notes |
|---|---|---|
| Total synapses in resource | **54,492,922** | = Σ(Connectivity) over all edges; matches Nature ">54.5M" |
| Unique neuron-pair edges (source parquet) | **15,091,983** | edges = distinct (pre, post) pairs |
| Edges with weight ≥ 1 (imported) | **15,091,983** (100%) | snapshot already thresholded at ≥1 |
| Edges with weight ≥ 2 | 7,595,967 | sensitivity bound |
| Edges with weight ≥ 5 | 2,700,513 | sensitivity bound |
| Collapsed edges | **15,091,983** | per-pair synapse counts aggregated into one edge each |
| Excluded | **0** | `load_connectivity(min_synapses=1)` drops weight < 1 (none exist) |
| Excitatory edges | 9,059,302 (60.0%) | `Excitatory == 1` |
| Inhibitory edges | 6,032,681 (40.0%) | `Excitatory == 0` |

**Collapse definition:** `Connectivity_*.parquet` is already the per-pair aggregate — each row is one (pre, post) neuron pair with `Connectivity` = synapse count between them (mean 3.61, median 2, max 2,405). NECTAR loads it as-is; no further collapsing or filtering is applied at import beyond the ≥1 synapse threshold (which removes zero rows).

## v630 (`Completeness_630.csv` + `Connectivity_630.parquet`)

| Stage | Count | Notes |
|---|---|---|
| Source roster (Completeness_630) | **127,400** | PhilShiu pre-annotation snapshot |
| Imported into NECTAR | **127,400** (100%) | all rows |
| Total synapses | **52,793,639** | = Σ(Connectivity) |
| Unique edges | **14,687,178** | all weight ≥ 1 |
| Excitatory edges | 8,800,532 (59.9%) | |
| Excluded | **0** | |

## Volume vs Nature network-statistics snapshot

The Nature *Network statistics* paper reports its own v630 materialization as
**127,978 neurons and 2.61M thresholded connections**. That is a *different*
snapshot: it is the "network-statistics" export (computationally thresholded to
strong/multi-synapse connections). NECTAR imports the **PhilShiu computational
snapshot** instead:

| Materialization | Neurons | Connections |
|---|---|---|
| FlyWire full resource | ~140k | >54.5M synapses |
| **NECTAR v783 (PhilShiu)** | **138,639** | **54.49M synapses / 15.09M pair-edges** |
| NECTAR v630 (PhilShiu) | 127,400 | 52.79M synapses / 14.69M pair-edges |
| Nature v630 network-statistics | 127,978 | 2.61M thresholded |

The 127,400 vs 127,978 gap (578 neurons) reflects different filtering rules in
the two materializations; NECTAR uses the paper's own files for apples-to-apples
validation (EXP-SUGAR-001).

## Statement (required qualification)

> "NECTAR imports the full FlyWire synaptic resource as published for the
> PhilShiu computational model: **138,639 neurons and 54.49M synapses (15.09M
> collapsed neuron-pair edges)**, 0 neurons excluded, 100% roster coverage.
> It does NOT import the separate network-statistics materialization (2.61M
> thresholded connections)."

## Raw sources (for audit)

- `data/nectar/connectome/Completeness_783.csv` (3.5 MB)
- `data/nectar/connectome/Connectivity_783.parquet` (100.8 MB)
- `data/nectar/connectome/Completeness_630.csv`, `Connectivity_630.parquet`
- SHA-256 of all inputs pinned in `data/nectar/repro/NECTAR-v0.1-FROZEN/manifest.json`