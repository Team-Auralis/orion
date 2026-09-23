"""
Game Expert Lab: Action Space
============================
Defines discrete action space and transition directions for GridWorld.
"""

from enum import IntEnum
from typing import List, Tuple


class Action(IntEnum):
    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3


ACTION_DELTAS: dict[Action, Tuple[int, int]] = {
    Action.UP: (-1, 0),
    Action.DOWN: (1, 0),
    Action.LEFT: (0, -1),
    Action.RIGHT: (0, 1),
}


class ActionSpace:
    """Discrete action space wrapper."""

    def __init__(self, actions: List[Action] = None):
        self.actions = actions or list(Action)
        self.n = len(self.actions)

    def sample(self) -> Action:
        import random
        return random.choice(self.actions)

    def is_valid(self, action: int) -> bool:
        return action in [a.value for a in self.actions]
