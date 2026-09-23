"""Benchmark and ablation registry — what to measure, with what controls."""

BENCHMARKS = {
    "BENCH-001": {
        "name": "Phase 1 anatomical validation",
        "metric": "mean_rate_hz per group matches Zheng/PhilShiu within 20%",
        "controls": ["background_stimulus", "differentiated_odors"],
        "ablation": ["no_lateral_inhibition"],
        "run_time_budget_s": 300,
        "report_fields": ["wall_time_s", "peak_ram_mb", "peak_vram_mb"],
    },
    "BENCH-002": {
        "name": "Null-backend integrity check",
        "metric": "output.mock == True",
        "controls": [],
        "ablation": [],
        "run_time_budget_s": 5,
        "report_fields": ["output.mock"],
    },
}


def list_benchmarks():
    return {k: v["name"] for k, v in BENCHMARKS.items()}


def get_benchmark(bench_id: str) -> dict:
    if bench_id not in BENCHMARKS:
        raise KeyError(f"Unknown benchmark {bench_id!r}.")
    return BENCHMARKS[bench_id]