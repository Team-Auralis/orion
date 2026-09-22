"""
Game Expert Lab Verification Suite
==================================
Tests modular RL dynamics, state abstraction, and empirical transfer learning:
- GridWorld step/reset semantics and boundary collisions
- Q-learning TD updates and knowledge serialization
- Relational state abstraction invariant representation
- Transfer experiment comparing COLD_ORION vs GAME_EXPERIENCED_ORION
"""

import pytest
from modules.game_lab.action_space import Action, ActionSpace
from modules.game_lab.environment import GridWorldEnv
from modules.game_lab.agent import QLearningAgent
from modules.game_lab.game_adapter import RelationalStateAdapter
from modules.game_lab.evaluator import TransferEvaluator


def test_gridworld_env_dynamics():
    env = GridWorldEnv(
        height=3,
        width=3,
        start_pos=(0, 0),
        goal_pos=(2, 2),
        hazards={(1, 1)},
        walls={(0, 1)},
    )
    env.reset()

    # Step into wall -> stays in place
    next_pos, reward, done, info = env.step(Action.RIGHT)
    assert next_pos == (0, 0)
    assert info["hit_wall"] is True
    assert done is False

    # Step down -> moves to (1, 0)
    next_pos, reward, done, info = env.step(Action.DOWN)
    assert next_pos == (1, 0)
    assert info["hit_wall"] is False

    # Step right into hazard -> terminal hazard
    next_pos, reward, done, info = env.step(Action.RIGHT)
    assert next_pos == (1, 1)
    assert info["hit_hazard"] is True
    assert done is True
    assert reward < 0


def test_qlearning_agent_learning_and_transfer():
    agent = QLearningAgent(lr=0.5, gamma=0.9, epsilon=0.0)
    s1, a1, r1, s2 = "state_1", Action.UP.value, 10.0, "state_2"

    assert agent.get_q(s1, a1) == 0.0
    agent.update(s1, a1, r1, s2, done=True)
    assert agent.get_q(s1, a1) == 5.0  # lr * (10 - 0) = 5.0

    # Test knowledge export and import
    exported = agent.export_knowledge()
    new_agent = QLearningAgent()
    assert new_agent.get_q(s1, a1) == 0.0
    new_agent.import_knowledge(exported)
    assert new_agent.get_q(s1, a1) == 5.0


def test_relational_state_adapter():
    pos = (1, 1)
    goal = (3, 3)
    hazards = {(0, 1), (1, 2)}  # UP and RIGHT blocked
    bounds = (4, 4)

    dir_r, dir_c, mask = RelationalStateAdapter.abstract_state(
        pos, goal, hazards, bounds
    )

    assert dir_r == 1  # Goal is below
    assert dir_c == 1  # Goal is right
    assert mask[Action.UP] is True  # UP is blocked by hazard
    assert mask[Action.RIGHT] is True  # RIGHT is blocked by hazard
    assert mask[Action.DOWN] is False  # DOWN is clear
    assert mask[Action.LEFT] is False  # LEFT is clear


def test_transfer_experiment_advantage():
    result = TransferEvaluator.run_transfer_benchmark(
        source_episodes=50,
        target_episodes=40,
        seed=42,
    )

    assert result.source_episodes == 50
    assert result.target_episodes == 40
    # The transfer claim is only meaningful if the two agents differ in prior
    # experience, not in hyperparameters (COLD used to train at lr=0.15 vs
    # EXPERIENCED's 0.2, which confounded the comparison).
    assert TransferEvaluator._cold_agent_lr == TransferEvaluator._experienced_agent_lr
    # Report whatever the evidence says, consistently.
    if result.accumulated_empirical_advantage > 0.0:
        assert result.transfer_occurred is True
        assert "EXPERTISE TRANSFERRED" in result.conclusion
    else:
        assert result.transfer_occurred is False
        assert "NEGATIVE OR NEUTRAL TRANSFER" in result.conclusion
    assert (
        result.experienced_mean_return != result.cold_mean_return
        or result.accumulated_empirical_advantage == 0.0
    )
