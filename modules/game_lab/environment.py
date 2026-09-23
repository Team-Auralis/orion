"""
Game Expert Lab: GridWorld Environment
======================================
Deterministic 2D GridWorld with customizable dimensions, obstacles, hazards, and goals.
"""

from typing import Tuple, Set, Dict, Any, Optional
from modules.game_lab.action_space import Action, ACTION_DELTAS, ActionSpace
from modules.game_lab.reward import RewardFunction, RewardConfig


class GridWorldEnv:
    """Discrete 2D Grid navigation environment."""

    def __init__(
        self,
        height: int = 4,
        width: int = 4,
        start_pos: Tuple[int, int] = (0, 0),
        goal_pos: Tuple[int, int] = (3, 3),
        hazards: Optional[Set[Tuple[int, int]]] = None,
        walls: Optional[Set[Tuple[int, int]]] = None,
        max_steps: int = 50,
        reward_config: Optional[RewardConfig] = None,
    ):
        self.height = height
        self.width = width
        self.start_pos = start_pos
        self.goal_pos = goal_pos
        self.hazards = hazards or set()
        self.walls = walls or set()
        self.max_steps = max_steps
        self.reward_fn = RewardFunction(reward_config)
        self.action_space = ActionSpace()

        self.agent_pos = start_pos
        self.current_step = 0

    def reset(self) -> Tuple[int, int]:
        self.agent_pos = self.start_pos
        self.current_step = 0
        return self.agent_pos

    def step(self, action: int) -> Tuple[Tuple[int, int], float, bool, Dict[str, Any]]:
        self.current_step += 1
        act = Action(action)
        dr, dc = ACTION_DELTAS[act]
        new_r, new_c = self.agent_pos[0] + dr, self.agent_pos[1] + dc

        hit_wall = False
        hit_hazard = False
        hit_goal = False

        # Check boundary collision
        if not (0 <= new_r < self.height and 0 <= new_c < self.width):
            hit_wall = True
            new_r, new_c = self.agent_pos  # Stay in place
        elif (new_r, new_c) in self.walls:
            hit_wall = True
            new_r, new_c = self.agent_pos  # Cannot step into wall
        else:
            self.agent_pos = (new_r, new_c)

        if self.agent_pos in self.hazards:
            hit_hazard = True
        elif self.agent_pos == self.goal_pos:
            hit_goal = True

        reward = self.reward_fn.compute(hit_goal=hit_goal, hit_hazard=hit_hazard, hit_wall=hit_wall)
        done = hit_goal or hit_hazard or (self.current_step >= self.max_steps)

        info = {
            "step": self.current_step,
            "hit_goal": hit_goal,
            "hit_hazard": hit_hazard,
            "hit_wall": hit_wall,
        }

        return self.agent_pos, reward, done, info
