"""DeviceEnvelope: the declared capability contract for one hive device.

This is the seam where real machines/phones slot in: a device describes
itself (role, cpu/ram budgets, measured tok/s, transport) and the coordinator
dispatches work by role + capability. Supports multiprocessing pipes and TCP sockets.
"""

from __future__ import annotations

import dataclasses
import platform

ROLE_PRIMARY = "primary_trainer"
ROLE_EVAL = "eval"
ROLE_LIGHTWEIGHT = "lightweight"

ROLES = (ROLE_PRIMARY, ROLE_EVAL, ROLE_LIGHTWEIGHT)


@dataclasses.dataclass(frozen=True)
class DeviceEnvelope:
    """A device's self-declared capability, exchanged at registration."""

    device_id: str
    role: str
    cpu_threads_budget: int
    ram_mb_budget: int
    tokens_per_sec_estimate: float = 0.0  # filled by the device's own probe
    transport: str = "multiprocessing-pipe"
    platform: str = ""

    def asdict(self) -> dict:
        return dataclasses.asdict(self)

    def with_tps(self, tps: float) -> "DeviceEnvelope":
        return DeviceEnvelope(
            device_id=self.device_id,
            role=self.role,
            cpu_threads_budget=self.cpu_threads_budget,
            ram_mb_budget=self.ram_mb_budget,
            tokens_per_sec_estimate=round(tps, 1),
            transport=self.transport,
            platform=self.platform,
        )


def declare_device(
    device_id: str,
    role: str,
    cpu_threads_budget: int,
    ram_mb_budget: int = 768,
    tps: float = 0.0,
    transport: str = "multiprocessing-pipe",
) -> DeviceEnvelope:
    if role not in ROLES:
        raise ValueError(f"unknown hive role {role!r}")
    return DeviceEnvelope(
        device_id=device_id,
        role=role,
        cpu_threads_budget=cpu_threads_budget,
        ram_mb_budget=ram_mb_budget,
        tokens_per_sec_estimate=tps,
        transport=transport,
        platform=f"{platform.system()}-{platform.machine()}",
    )
