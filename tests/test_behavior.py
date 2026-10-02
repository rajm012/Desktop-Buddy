"""Unit tests for the pure-python behaviour engine."""

from __future__ import annotations

import random
import unittest

from desktop_buddy.behavior import Brain, Event, State, World


def make_brain(**kwargs: object) -> Brain:
    world = World(left=0.0, right=1000.0, ground=800.0)
    brain = Brain(world=world, rng=random.Random(7), **kwargs)
    brain.x = 500.0
    brain.y = 800.0
    return brain


def run(brain: Brain, seconds: float, dt: float = 1.0 / 60.0) -> list[Event]:
    events: list[Event] = []
    steps = int(seconds / dt)
    for _ in range(steps):
        events.extend(brain.step(dt))
    return events


class PhysicsTests(unittest.TestCase):
    def test_poke_jumps_and_lands(self) -> None:
        brain = make_brain()
        self.assertIn(Event.JUMP, brain.poke())
        self.assertIs(brain.state, State.AIR)
        events = run(brain, 3.0)
        self.assertIn(Event.LAND, events)
        self.assertAlmostEqual(brain.y, brain.world.ground)
        self.assertIs(brain.state, State.IDLE)

    def test_walk_reaches_target(self) -> None:
        brain = make_brain()
        brain._start_walk()
        target = brain._target_x
        self.assertIs(brain.state, State.WALK)
        closest = abs(brain.x - target)
        for _ in range(int(20.0 * 60)):
            brain.step(1.0 / 60.0)
            closest = min(closest, abs(brain.x - target))
        self.assertLess(closest, 2.0)

    def test_air_bounces_off_screen_edge(self) -> None:
        brain = make_brain()
        brain.state = State.AIR
        brain.y = 700.0
        brain.x = 990.0
        brain.vx = 300.0
        brain.step(1.0 / 60.0)
        self.assertLessEqual(brain.x, brain.world.right - brain.tuning.edge_margin)
        self.assertLessEqual(brain.vx, 0.0)

    def test_drag_clamps_to_world(self) -> None:
        brain = make_brain()
        brain.start_drag()
        brain.drag_to(-500.0, -300.0, now=0.0)
        self.assertGreaterEqual(brain.x, brain.world.left + brain.tuning.edge_margin)
        self.assertGreaterEqual(brain.y, brain.world.ceiling + 26.0)
        brain.drag_to(5000.0, 5000.0, now=0.1)
        self.assertLessEqual(brain.x, brain.world.right - brain.tuning.edge_margin)
        self.assertEqual(brain.y, brain.world.ground)
        brain.end_drag()
        self.assertIsNot(brain.state, State.DRAG)

    def test_drag_velocity_estimate(self) -> None:
        brain = make_brain()
        brain.start_drag()
        brain.drag_to(500.0, 800.0, now=0.0)
        brain.drag_to(600.0, 800.0, now=0.1)
        brain.drag_to(700.0, 800.0, now=0.2)
        vx, vy = brain.drag_velocity()
        self.assertAlmostEqual(vx, 1000.0, delta=1.0)
        self.assertAlmostEqual(vy, 0.0, delta=1.0)


class BehaviourTests(unittest.TestCase):
    def test_falls_asleep_after_timeout(self) -> None:
        brain = make_brain(can_sleep=True, sleep_after=2.0)
        brain._idle_since_interaction = 5.0
        brain._idle_left = 0.01
        brain.step(0.05)
        self.assertIs(brain.state, State.SLEEP)

    def test_interaction_wakes_sleeping_buddy(self) -> None:
        brain = make_brain(can_sleep=True, sleep_after=1.0)
        brain.state = State.SLEEP
        brain.note_interaction()
        self.assertIsNot(brain.state, State.SLEEP)

    def test_cursor_tracking_moves_gaze(self) -> None:
        brain = make_brain()
        brain.set_cursor(900.0, 750.0)
        run(brain, 1.0)
        self.assertGreater(brain.look[0], 0.2)

    def test_blink_is_bounded(self) -> None:
        brain = make_brain()
        for _ in range(600):
            brain.step(1.0 / 60.0)
            self.assertGreaterEqual(brain.blink, 0.0)
            self.assertLessEqual(brain.blink, 1.0)

    def test_never_leaves_world_horizontally(self) -> None:
        brain = make_brain()
        margin = brain.tuning.edge_margin
        for _ in range(60 * 60):
            brain.step(1.0 / 60.0)
            self.assertGreaterEqual(brain.x, brain.world.left + margin - 1.0)
            self.assertLessEqual(brain.x, brain.world.right - margin + 1.0)


if __name__ == "__main__":
    unittest.main()
