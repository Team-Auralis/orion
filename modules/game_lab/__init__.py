"""
ORION Game Expert Lab
=====================
Modular reinforcement learning and knowledge transfer laboratory:
- Action space & transitions
- Environmental dynamics
- Experience replay
- Q-learning with knowledge export/import
- Relational abstraction for cross-domain transfer
- Comparative transfer evaluation (COLD vs EXPERIENCED)
"""

from modules.game_lab.action_space import Action, ActionSpace
from modules.game_lab.reward import RewardFunction, RewardConfig
from modules.game_lab.environment import GridWorldEnv
from modules.game_lab.replay_buffer import ReplayBuffer, Transition
from modules.game_lab.agent import QLearningAgent
from modules.game_lab.game_adapter import RelationalStateAdapter
from modules.game_lab.evaluator import TransferEvaluator, TransferExperimentResult

__all__ = [
    "Action",
    "ActionSpace",
    "RewardFunction",
    "RewardConfig",
    "GridWorldEnv",
    "ReplayBuffer",
    "Transition",
    "QLearningAgent",
    "RelationalStateAdapter",
    "TransferEvaluator",
    "TransferExperimentResult",
]
