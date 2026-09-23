"""
Game Expert Lab: Reward Function
================================
Defines reward functions and penalties for GridWorld navigation:
- Step penalty (encourages optimal shortest path)
- Goal reward (reward for reaching target)
- Hazard penalty (penalty for stepping into obstacle / failure zone)
- Boundary collision penalty
"""

from dataclasses import dataclass


@dataclass
class RewardConfig:
    step_penalty: float = -0.05
    goal_reward: float = 10.0
    hazard_penalty: float = -5.0
    collision_penalty: float = -0.5


class RewardFunction:
    """Computes scalar reward for state transitions."""

    def __init__(self, config: RewardConfig = None):
        self.cfg = config or RewardConfig()

    def compute(self, hit_goal: bool, hit_hazard: bool, hit_wall: bool) -> float:
        if hit_goal:
            return self.cfg.goal_reward
        if hit_hazard:
            return self.cfg.hazard_penalty
        if hit_wall:
            return self.cfg.collision_penalty + self.cfg.step_penalty
        return self.cfg.step_penalty
