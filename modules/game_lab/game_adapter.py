"""
Game Expert Lab: Game Adapter & Representation Translator
=======================================================
Separates game-specific mechanics from transferable civilizational representations:
- Abstracts raw coordinate indices (r, c) into invariant spatial relations:
  (relative_goal_direction, hazard_proximity_mask, boundary_clearance)
- Allows knowledge learned in small/source domains to transfer directly
  to larger, open-world environments.
"""

from typing import Tuple, Dict, Any, Set
from modules.game_lab.action_space import Action, ACTION_DELTAS


class RelationalStateAdapter:
    """Translates raw grid coordinates into invariant spatial relation features."""

    @staticmethod
    def abstract_state(
        pos: Tuple[int, int],
        goal: Tuple[int, int],
        hazards: Set[Tuple[int, int]],
        grid_bounds: Tuple[int, int],
    ) -> Tuple[int, int, Tuple[bool, bool, bool, bool]]:
        """
        Produce invariant representation:
        - delta_r: sign of (goal_r - pos_r) -> -1, 0, 1
        - delta_c: sign of (goal_c - pos_c) -> -1, 0, 1
        - hazard_mask: 4-tuple indicating whether UP, DOWN, LEFT, RIGHT has a hazard/wall
        """
        r, c = pos
        gr, gc = goal
        h, w = grid_bounds

        dir_r = 0 if gr == r else (1 if gr > r else -1)
        dir_c = 0 if gc == c else (1 if gc > c else -1)

        # Check adjacent hazards or boundaries
        def is_blocked(dr: int, dc: int) -> bool:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < h and 0 <= nc < w):
                return True
            if (nr, nc) in hazards:
                return True
            return False

        blocked_mask = (
            is_blocked(*ACTION_DELTAS[Action.UP]),
            is_blocked(*ACTION_DELTAS[Action.DOWN]),
            is_blocked(*ACTION_DELTAS[Action.LEFT]),
            is_blocked(*ACTION_DELTAS[Action.RIGHT]),
        )

        return (dir_r, dir_c, blocked_mask)
