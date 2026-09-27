import json

for tag in ["base", "v6", "v7"]:
    s = json.load(open(f"logs/gen_probe_summary_{tag}.json", encoding="utf-8"))
    print("==== tag", tag, "====")
    for name, a in s["sets"].items():
        print(
            f"  {name:12s} n={a['n']:2d} latch={a['latch_rate']:.2f} "
            f"clean={a['clean_rate']:.2f} stop={a['stop_rate']:.2f} "
            f"len={a['avg_len_tokens']:5.1f} distinct={a['avg_distinct_ratio']:.2f} "
            f"contain={a['ref_contain_rate']} exact={a['ref_exact_rate']} "
            f"first3={a['ref_first3_rate']}"
        )
