"""FORGE -> NECTAR -> OMNIS pipeline smoke test.

Verifies the full dispatch contract without a live Postgres:
  submit_protocol -> run -> evidence_into_omnis -> OmnisObservation row.

Uses an in-memory SQLite Session and the MOCK NullBackend, so it is safe to
run in CI and on machines with no simulator. Real experiments use Brian2Backend
and write evidence the same way.
"""
import sys
import os
import json
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api import database
from services.nectar.core import NectarEngine
from services.nectar.simulator.null_backend import NullBackend


def main():
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)

    exp_id = f"EXP-SMOKE-{uuid.uuid4().hex[:8]}"
    with Session(engine) as db:
        exp = database.ForgeExperiment(
            id=exp_id,
            hypothesis="NECTAR dispatch contract works",
            experiment_design=json.dumps({"name": "forge_smoke"}),
            status="PROPOSED",
        )
        db.add(exp)
        db.commit()

        engine_inst = NectarEngine(db, NullBackend())
        submitted = engine_inst.submit_protocol(
            exp_id,
            "dummy_connectome.parquet",
            {"completeness_path": "dummy.csv"},
            {"duration_s": 0.1, "dt": 0.001},
        )
        assert submitted["status"] == "LOADED", submitted

        result = engine_inst.run(0.1, 0.001, ["antennal_lobe", "mushroom_body"])
        readout = result["readout"]
        assert readout["mock"] is True, "NullBackend must be explicitly MOCK"

        ok = engine_inst.evidence_into_omnis(exp_id, "entity_fly", readout, score=0.9)
        assert ok, "evidence write failed"

        obs = db.query(database.OmnisObservation).first()
        assert obs is not None and obs.entity_id == "entity_fly"
        state = json.loads(obs.state_data)
        assert state["source"] == "NECTAR"
        assert state["backend"] == "null"

    print("FORGE -> NECTAR -> OMNIS PIPELINE OK")
    print(f"  experiment={exp_id}")
    print("  submit_protocol -> RUNNING -> evidence row committed")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)