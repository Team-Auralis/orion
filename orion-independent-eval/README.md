# ORION Independent Evaluator v3.0

An adversarial, zero-trust evaluation engine designed to empirically verify Project ORION without importing its internal implementations to compute expected results.

## Structure

```
orion-independent-eval/
├── generators/
│   └── hidden_generator.py           # Dynamic, randomized boundary input generator
├── oracles/
│   └── reference_oracles.py          # Pure independent reference oracles (GEO, CRDT, Cyber, Validation)
├── metamorphic/
│   └── metamorphic_harness.py        # Symmetry, identity, and commutativity invariant tests
├── mutations/
│   └── adversarial_implementations.py# HARD-01 to HARD-04 fake templates & MUT-01 to MUT-02 mutations
├── runners/
│   └── run_eval.py                   # Main runner: self-test, execution, scoring
├── results/
│   └── results.json                  # Machine-readable output metrics and unverified flags
├── evaluation_environment.json       # Frozen commit hash, platform, and python environment
└── README.md
```

## Running the Benchmark

```bash
python orion-independent-eval/runners/run_eval.py
```
