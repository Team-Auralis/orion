import os

import pandas as pd


COLUMN_SCHEMAS = {
    "flywire": {
        "pre": "pre_root_id",
        "post": "post_root_id",
        "weight": "synapse_count",
        "sign": None,
        "pre_idx": None,
        "post_idx": None,
    },
    "philshiu": {
        "pre": "Presynaptic_ID",
        "post": "Postsynaptic_ID",
        "weight": "Connectivity",
        "sign": "Excitatory",
        "pre_idx": "Presynaptic_Index",
        "post_idx": "Postsynaptic_Index",
    },
}


def detect_schema(df: pd.DataFrame) -> str:
    if "pre" in df.columns and "weight" in df.columns:
        return "canonical"
    if "synapse_count" in df.columns:
        return "flywire"
    if "Connectivity" in df.columns:
        return "philshiu"
    raise ValueError(
        "Unknown connectivity schema. Requires synapse_count or Connectivity column."
    )


def normalize(df: pd.DataFrame, schema: str = None) -> pd.DataFrame:
    """Normalize any supported connectivity table into canonical columns."""
    if schema is None:
        schema = detect_schema(df)
    if schema == "canonical":
        out = df[["pre", "post", "weight"]].copy()
        if "sign" in df.columns:
            out["sign"] = df["sign"].astype(float).copy()
        if "pre_idx" in df.columns:
            out["pre_idx"] = df["pre_idx"].copy()
        if "post_idx" in df.columns:
            out["post_idx"] = df["post_idx"].copy()
        return out
    spec = COLUMN_SCHEMAS[schema]

    out = pd.DataFrame({
        "pre": df[spec["pre"]],
        "post": df[spec["post"]],
        "weight": df[spec["weight"]],
    })
    if spec.get("sign") and spec["sign"] in df.columns:
        out["sign"] = df[spec["sign"]].astype(float)
    if spec.get("pre_idx") and spec["pre_idx"] in df.columns:
        out["pre_idx"] = df[spec["pre_idx"]]
    if spec.get("post_idx") and spec["post_idx"] in df.columns:
        out["post_idx"] = df[spec["post_idx"]]
    return out


def load_connectivity(path: str, min_synapses: int = 1) -> pd.DataFrame:
    """
    Load a FlyWire / PhilShiu connectivity table.

    Recognized schemas:
      - flywire:  pre_root_id, post_root_id, synapse_count
      - philshiu: Presynaptic_ID, Postsynaptic_ID, Connectivity,
                  optional Excitatory sign and *_Index precomputed ids

    Supports .parquet, .feather, .csv, .csv.gz.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Connectivity not found: {path}")

    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    elif path.endswith(".feather"):
        df = pd.read_feather(path)
    elif path.endswith(".gz"):
        df = pd.read_csv(path, compression="gzip")
    else:
        df = pd.read_csv(path)

    df = normalize(df)
    return df[df["weight"] >= min_synapses].reset_index(drop=True)


def load_completeness(path: str) -> pd.DataFrame:
    """
    Load the PhilShiu completeness materialization (neuron roster).

    Index = flywire root ids, sorted. The row ORDER defines the Brian2
    neuron ids (matching Presynaptic_Index / Postsynaptic_Index).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Completeness not found: {path}")
    df = pd.read_csv(path, index_col=0)
    if df.index.dtype != "int64":
        df.index = df.index.astype("int64")
    return df


def build_id_map(df: pd.DataFrame):
    """
    Map 64-bit root ids to compact contiguous integer neuron ids.
    Returns (id_map, reverse_map).
    """
    ids = sorted(set(df["pre"]) | set(df["post"]))
    id_map = {rid: i for i, rid in enumerate(ids)}
    reverse_map = {i: rid for rid, i in id_map.items()}
    return id_map, reverse_map


def to_adjacency(df: pd.DataFrame, id_map: dict = None) -> dict:
    """Build source-to-target adjacency for numerical simulation."""
    if id_map is None:
        if "pre_idx" in df.columns:
            pre_idx = df["pre_idx"].to_numpy()
            post_idx = df["post_idx"].to_numpy()
        else:
            id_map, _ = build_id_map(df)
            pre_idx = df["pre"].map(id_map).to_numpy()
            post_idx = df["post"].map(id_map).to_numpy()
    else:
        pre_idx = df["pre"].map(id_map).to_numpy()
        post_idx = df["post"].map(id_map).to_numpy()

    adjacency = {}
    for pre, post, weight in zip(pre_idx, post_idx, df["weight"]):
        adjacency.setdefault(int(pre), []).append((int(post), float(weight)))
    return adjacency