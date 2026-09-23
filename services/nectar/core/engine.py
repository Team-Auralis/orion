import uuid
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.database import ForgeExperiment, OmnisObservation

from .backend import NectarBackend


class NectarEngine:
    """
    Orchestrates NECTAR experiments on behalf of FORGE.

    Flow: resolve backend -> load connectome subset -> run protocol ->
    produce structured readout -> write evidence into OMNIS.
    """

    def __init__(self, db_session: Session, backend: NectarBackend):
        self.db = db_session
        self.backend = backend
        self._run_id = None

    def submit_protocol(self, experiment_id: str, connectome_path: str,
                        constraints: dict, protocol: dict) -> dict:
        experiment = self.db.query(ForgeExperiment).filter_by(id=experiment_id).first()
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found.")

        experiment.status = "RUNNING"
        self.db.commit()

        self._run_id = str(uuid.uuid4())
        self.backend.load_connectome(connectome_path, constraints)

        return {
            "run_id": self._run_id,
            "backend": self.backend.name,
            "status": "LOADED",
        }

    def run(self, duration: float, dt: float, groups: list) -> dict:
        if not self._run_id:
            raise NectarBackendError("No run initialized; call submit_protocol first.")

        self.backend.stimulate([], "background", duration)
        steps = int(duration / dt)
        for _ in range(steps):
            self.backend.step(dt)

        readout = self.backend.readout(groups)
        return {"run_id": self._run_id, "readout": readout}

    def evidence_into_omnis(self, experiment_id: str, target_entity_id: str,
                            readout: dict, score: float) -> bool:
        """Write verified empirical findings into the OMNIS world model."""
        experiment = self.db.query(ForgeExperiment).filter_by(id=experiment_id).first()
        if not experiment or score < 0.8:
            return False

        observation = OmnisObservation(
            id=str(uuid.uuid4()),
            entity_id=target_entity_id,
            state_data=json.dumps({
                "source": "NECTAR",
                "backend": self.backend.name,
                "run_id": self._run_id,
                "readout": readout,
                "evidence_id": experiment.id,
            }),
            provenance=f"NECTAR:{self.backend.name}",
        )
        self.db.add(observation)
        self.db.commit()
        return True