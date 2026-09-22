"""
Game Expert Lab: Evaluator & Transfer Experiment Runner
======================================================
Empirically tests whether expertise accumulates and transfers:
  COLD_ORION (Tabula Rasa) vs GAME_EXPERIENCED_ORION (Pre-trained on Source Domain)
Evaluates on an unseen Target Domain and computes Accumulated Empirical Advantage (AEA).
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from modules.game_lab.environment import GridWorldEnv
from modules.game_lab.agent import QLearningAgent
from modules.game_lab.game_adapter import RelationalStateAdapter


@dataclass
class TransferExperimentResult:
    source_episodes: int
    target_episodes: int
    cold_mean_return: float
    cold_success_rate: float
    cold_first_episode_return: float
    experienced_mean_return: float
    experienced_success_rate: float
    experienced_first_episode_return: float
    accumulated_empirical_advantage: float
    transfer_occurred: bool
    conclusion: str


class TransferEvaluator:
    """Orchestrates controlled comparative transfer experiments."""

    # Shared hyperparameters for both agents. The transfer comparison is only
    # meaningful if COLD and EXPERIENCED differ in prior experience, not in
    # learning rate — COLD used to train at 0.15 vs EXPERIENCED's 0.2, which
    # confounded the advantage.
    _cold_agent_lr = 0.2
    _experienced_agent_lr = 0.2

    @staticmethod
    def train_agent(
        env: GridWorldEnv,
        agent: QLearningAgent,
        episodes: int,
        use_relational: bool = True,
    ) -> List[float]:
        returns = []
        for ep in range(episodes):
            raw_state = env.reset()
            state = (
                RelationalStateAdapter.abstract_state(
                    raw_state,
                    env.goal_pos,
                    env.hazards | env.walls,
                    (env.height, env.width),
                )
                if use_relational
                else raw_state
            )

            ep_return = 0.0
            done = False
            while not done:
                action = agent.select_action(state)
                next_raw, reward, done, info = env.step(action)
                next_state = (
                    RelationalStateAdapter.abstract_state(
                        next_raw,
                        env.goal_pos,
                        env.hazards | env.walls,
                        (env.height, env.width),
                    )
                    if use_relational
                    else next_raw
                )
                agent.update(state, action, reward, next_state, done)
                state = next_state
                ep_return += reward

            agent.decay_exploration()
            returns.append(round(ep_return, 3))
        return returns

    @classmethod
    def run_transfer_benchmark(
        cls,
        source_episodes: int = 40,
        target_episodes: int = 30,
        seed: int = 42,
    ) -> TransferExperimentResult:
        import random

        random.seed(seed)

        # 1. Define Diverse Source Environments (teaches general goal-seeking and hazard avoidance)
        source_env_1 = GridWorldEnv(
            height=3,
            width=3,
            start_pos=(0, 0),
            goal_pos=(2, 2),
            hazards={(1, 0)},
            walls=set(),
            max_steps=20,
        )
        source_env_2 = GridWorldEnv(
            height=3,
            width=3,
            start_pos=(0, 0),
            goal_pos=(2, 2),
            hazards={(0, 1)},
            walls=set(),
            max_steps=20,
        )

        # 2. Pre-train GAME_EXPERIENCED_ORION on Source Environments
        experienced_agent = QLearningAgent(
            lr=TransferEvaluator._experienced_agent_lr, gamma=0.9, epsilon=0.3
        )
        cls.train_agent(
            source_env_1, experienced_agent, source_episodes // 2, use_relational=True
        )
        cls.train_agent(
            source_env_2, experienced_agent, source_episodes // 2, use_relational=True
        )
        # Reset exploration for adaptation on novel target domain
        experienced_agent.epsilon = 0.25

        # 3. Define Target Environment (4x4 grid with novel hazards and walls)
        target_env_cold = GridWorldEnv(
            height=4,
            width=4,
            start_pos=(0, 0),
            goal_pos=(3, 3),
            hazards={(2, 1)},
            walls={(1, 2)},
            max_steps=30,
        )
        target_env_exp = GridWorldEnv(
            height=4,
            width=4,
            start_pos=(0, 0),
            goal_pos=(3, 3),
            hazards={(2, 1)},
            walls={(1, 2)},
            max_steps=30,
        )

        # 4. Initialize COLD_ORION (fresh agent with no memory).
        # Same hyperparameters as the experienced agent — differing only in
        # prior experience — so the transfer comparison is not confounded by
        # learning rate (was lr=0.15 vs experienced lr=0.2 before).
        cold_agent = QLearningAgent(
            lr=TransferEvaluator._cold_agent_lr, gamma=0.9, epsilon=0.25
        )

        # 5. Evaluate both agents on Target Environment
        cold_returns = cls.train_agent(
            target_env_cold, cold_agent, target_episodes, use_relational=True
        )
        exp_returns = cls.train_agent(
            target_env_exp, experienced_agent, target_episodes, use_relational=True
        )

        cold_mean = sum(cold_returns) / len(cold_returns)
        exp_mean = sum(exp_returns) / len(exp_returns)
        aea = exp_mean - cold_mean

        # Calculate success rates (reaching goal has reward >= 5.0)
        cold_successes = sum(1 for r in cold_returns if r >= 5.0)
        exp_successes = sum(1 for r in exp_returns if r >= 5.0)

        cold_succ_rate = cold_successes / len(cold_returns)
        exp_succ_rate = exp_successes / len(exp_returns)

        transfer_occurred = aea > 0.5 and (exp_succ_rate >= cold_succ_rate)
        conclusion = (
            f"EXPERTISE TRANSFERRED: GAME_EXPERIENCED_ORION outperformed COLD_ORION by {aea:+.2f} mean reward "
            f"({exp_succ_rate * 100:.1f}% vs {cold_succ_rate * 100:.1f}% success rate)."
            if transfer_occurred
            else "NEGATIVE OR NEUTRAL TRANSFER: No measurable advantage detected."
        )

        return TransferExperimentResult(
            source_episodes=source_episodes,
            target_episodes=target_episodes,
            cold_mean_return=round(cold_mean, 2),
            cold_success_rate=round(cold_succ_rate, 3),
            cold_first_episode_return=cold_returns[0],
            experienced_mean_return=round(exp_mean, 2),
            experienced_success_rate=round(exp_succ_rate, 3),
            experienced_first_episode_return=exp_returns[0],
            accumulated_empirical_advantage=round(aea, 2),
            transfer_occurred=transfer_occurred,
            conclusion=conclusion,
        )
