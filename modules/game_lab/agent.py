"""
Game Expert Lab: Q-Learning Agent
=================================
Tabular Q-learning agent capable of accumulating and transferring policy knowledge.
"""

import random
from typing import Dict, Tuple, Any, Optional
from modules.game_lab.action_space import ActionSpace


class QLearningAgent:
    """Q-learning agent with experience retention and cross-task transfer capabilities."""

    def __init__(
        self,
        action_space: Optional[ActionSpace] = None,
        lr: float = 0.1,
        gamma: float = 0.95,
        epsilon: float = 0.2,
        min_epsilon: float = 0.01,
        epsilon_decay: float = 0.995,
    ):
        self.action_space = action_space or ActionSpace()
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.min_epsilon = min_epsilon
        self.epsilon_decay = epsilon_decay
        self.q_table: Dict[Tuple[Any, int], float] = {}

    def get_q(self, state: Any, action: int) -> float:
        return self.q_table.get((state, action), 0.0)

    def select_action(self, state: Any, greedy: bool = False) -> int:
        if not greedy and random.random() < self.epsilon:
            return self.action_space.sample().value

        # Greedy action selection breaking ties randomly
        q_vals = [self.get_q(state, a.value) for a in self.action_space.actions]
        max_q = max(q_vals)
        best_actions = [
            a.value for a, q in zip(self.action_space.actions, q_vals) if q == max_q
        ]
        return random.choice(best_actions)

    def update(self, state: Any, action: int, reward: float, next_state: Any, done: bool):
        current_q = self.get_q(state, action)
        if done:
            target = reward
        else:
            next_max_q = max(self.get_q(next_state, a.value) for a in self.action_space.actions)
            target = reward + self.gamma * next_max_q

        # Bellman update
        new_q = current_q + self.lr * (target - current_q)
        self.q_table[(state, action)] = round(new_q, 6)

    def decay_exploration(self):
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)

    def export_knowledge(self) -> Dict[Tuple[Any, int], float]:
        """Export learned state-action value knowledge."""
        return dict(self.q_table)

    def import_knowledge(self, knowledge: Dict[Tuple[Any, int], float]):
        """Warm-start agent using prior expertise."""
        self.q_table.update(knowledge)
