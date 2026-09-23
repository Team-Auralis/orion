"""
Game Expert Lab: Replay Buffer
==============================
Experience buffer storing state transitions (s, a, r, s', done) for RL training.
"""

import random
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple, Any


@dataclass
class Transition:
    state: Any
    action: int
    reward: float
    next_state: Any
    done: bool


class ReplayBuffer:
    """Fixed-capacity transition buffer for reinforcement learning."""

    def __init__(self, capacity: int = 5000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state: Any, action: int, reward: float, next_state: Any, done: bool):
        self.buffer.append(Transition(state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> List[Transition]:
        return random.sample(self.buffer, min(len(self.buffer), batch_size))

    def __len__(self) -> int:
        return len(self.buffer)
