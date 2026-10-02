"""Pure-python behaviour engine for the desktop buddy.

This module deliberately has no Qt dependency so it can be unit-tested
headlessly and reasoned about in isolation.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    WALK = "walk"
    RUN = "run"
    AIR = "air"
    LAND = "land"
    SLEEP = "sleep"
    DRAG = "drag"


class Event(str, Enum):
    JUMP = "jump"
    LAND = "land"
    WAKE = "wake"
    POKE = "poke"


BLINK_DURATION = 0.22


@dataclass(frozen=True)
class World:
    """Screen bounds in logical pixels. `ground` is the floor the buddy walks on."""

    left: float
    right: float
    ground: float
    ceiling: float = 0.0

    @property
    def width(self) -> float:
        return max(1.0, self.right - self.left)

    def clamp_x(self, x: float, margin: float) -> float:
        low = self.left + margin
        high = self.right - margin
        if low > high:
            return (self.left + self.right) / 2.0
        return max(low, min(high, x))


@dataclass
class Tuning:
    walk_speed: float = 62.0
    run_speed: float = 135.0
    gravity: float = 1500.0
    jump_velocity: float = 560.0
    land_duration: float = 0.16
    min_idle: float = 0.7
    max_idle: float = 3.2
    edge_margin: float = 46.0
    cursor_radius: float = 320.0
    wake_radius: float = 190.0
    walk_span: float = 260.0
    run_span: float = 420.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class Brain:
    """State machine + physics for one buddy."""

    world: World
    rng: random.Random = field(default_factory=random.Random)
    tuning: Tuning = field(default_factory=Tuning)
    speed_scale: float = 1.0
    playful: bool = True
    can_sleep: bool = True
    sleep_after: float = 180.0

    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    facing: int = 1
    state: State = State.IDLE
    state_time: float = 0.0
    anim_time: float = 0.0
    blink: float = 0.0
    look: tuple[float, float] = (0.0, 0.0)
    cursor: tuple[float, float] | None = None
    last_impact: float = 0.0

    _blink_countdown: float = 2.0
    _blink_phase: float = 0.0
    _idle_left: float = 1.0
    _target_x: float = 0.0
    _idle_since_interaction: float = 0.0
    _cursor_dwell: float = 0.0
    _drag_samples: list[tuple[float, float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.y == 0.0:
            self.y = self.world.ground
        if self.x == 0.0:
            self.x = (self.world.left + self.world.right) / 2.0

    # ------------------------------------------------------------- geometry
    @property
    def height(self) -> float:
        """Height above the ground (0 when standing)."""
        return max(0.0, self.world.ground - self.y)

    @property
    def airborne(self) -> bool:
        return self.state is State.AIR

    @property
    def grounded(self) -> bool:
        return self.state not in (State.AIR, State.DRAG)

    def head_position(self) -> tuple[float, float]:
        return (self.x, self.y - 52.0)

    # ------------------------------------------------------------ external api
    def set_cursor(self, x: float, y: float) -> None:
        self.cursor = (float(x), float(y))

    def note_interaction(self) -> None:
        self._idle_since_interaction = 0.0
        self._cursor_dwell = 0.0
        if self.state is State.SLEEP:
            self._wake()

    def poke(self) -> list[Event]:
        """Double-click interaction: a happy hop."""
        events: list[Event] = [Event.POKE]
        self.note_interaction()
        if self.state not in (State.AIR, State.DRAG):
            self._start_jump(events, direction=self.facing or 1, boost=1.2)
        return events

    def start_drag(self) -> None:
        self.note_interaction()
        self.state = State.DRAG
        self.state_time = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self._drag_samples = []

    def drag_to(self, x: float, y: float, now: float = 0.0) -> None:
        margin = self.tuning.edge_margin
        self.x = self.world.clamp_x(x, margin)
        self.y = max(self.world.ceiling + 26.0, min(self.world.ground, y))
        self._drag_samples.append((now, self.x, self.y))
        if len(self._drag_samples) > 5:
            self._drag_samples.pop(0)

    def end_drag(self, vx: float = 0.0, vy: float = 0.0) -> None:
        self.vx = max(-1200.0, min(1200.0, vx))
        self.vy = max(-1400.0, min(1400.0, vy))
        if self.y < self.world.ground - 4.0 or abs(self.vy) > 140.0:
            if self.vx > 20:
                self.facing = 1
            elif self.vx < -20:
                self.facing = -1
            self.state = State.AIR
        else:
            self._to_idle()
        self.state_time = 0.0

    def drag_velocity(self) -> tuple[float, float]:
        """Estimate the throw velocity (px/s) from recent drag samples."""
        if len(self._drag_samples) < 2:
            return (0.0, 0.0)
        t0, x0, y0 = self._drag_samples[0]
        t1, x1, y1 = self._drag_samples[-1]
        dt = max(0.001, t1 - t0)
        if dt < 1e-6:
            return (0.0, 0.0)
        return ((x1 - x0) / dt, (y1 - y0) / dt)

    # ------------------------------------------------------------------ loop
    def step(self, dt: float) -> list[Event]:
        dt = max(0.0, min(dt, 0.08))
        events: list[Event] = []
        self.anim_time += dt
        self.state_time += dt
        self._idle_since_interaction += dt
        self._update_blink(dt)
        self._update_gaze(dt)
        self._update_cursor_interest(dt)

        state = self.state
        if state is State.DRAG:
            self.vx = self.vy = 0.0
            return events

        if state is State.SLEEP:
            if self._cursor_near(self.tuning.wake_radius) or self._idle_since_interaction < 0.25:
                self._wake()
                events.append(Event.WAKE)
            return events

        if state is State.AIR:
            self._step_air(dt, events)
        elif state is State.LAND:
            if self.state_time >= self.tuning.land_duration:
                self._to_idle()
        elif state in (State.WALK, State.RUN):
            self._step_walk(dt, events)
        elif state is State.IDLE:
            self._step_idle(dt, events)
        return events

    # --------------------------------------------------------------- internals
    def _step_air(self, dt: float, events: list[Event]) -> None:
        self.vy += self.tuning.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        margin = self.tuning.edge_margin
        if self.x < self.world.left + margin:
            self.x = self.world.left + margin
            self.vx = abs(self.vx) * 0.8
            self.facing = 1
        elif self.x > self.world.right - margin:
            self.x = self.world.right - margin
            self.vx = -abs(self.vx) * 0.8
            self.facing = -1
        if self.y >= self.world.ground:
            self.last_impact = self.vy
            self.y = self.world.ground
            self.vx = 0.0
            self.vy = 0.0
            self.state = State.LAND
            self.state_time = 0.0
            events.append(Event.LAND)
        elif self.y < self.world.ceiling + 20.0:
            self.y = self.world.ceiling + 20.0
            self.vy = abs(self.vy) * 0.5

    def _step_walk(self, dt: float, events: list[Event]) -> None:
        speed = self.tuning.run_speed if self.state is State.RUN else self.tuning.walk_speed
        speed *= self.speed_scale
        direction = 1 if self._target_x >= self.x else -1
        self.facing = direction
        self.vx = direction * speed
        self.x += self.vx * dt
        distance = abs(self.x - self._target_x)
        if distance <= max(2.5, speed * dt):
            self.x = self._target_x
            self._to_idle()
        elif self.rng.random() < 0.13 * dt:
            self._start_jump(events, direction=direction)

    def _step_idle(self, dt: float, events: list[Event]) -> None:
        self.vx *= max(0.0, 1.0 - dt * 8.0)
        self._idle_left -= dt
        if self._idle_left <= 0.0:
            self._choose_action(events)

    def _choose_action(self, events: list[Event]) -> None:
        if self.can_sleep and self._idle_since_interaction >= self.sleep_after:
            self.state = State.SLEEP
            self.state_time = 0.0
            self._idle_left = 1.0
            return

        roll = self.rng.random()
        curious = (
            self.playful
            and self.cursor is not None
            and self._cursor_dwell > 1.0
            and self._cursor_near(self.tuning.cursor_radius)
        )
        if curious and roll < 0.65:
            cursor_x = self.cursor[0]  # type: ignore[index]
            side = 1 if self.x < cursor_x else -1
            self._target_x = self.world.clamp_x(
                cursor_x - side * 70.0, self.tuning.edge_margin
            )
            self.state = State.RUN
            self.state_time = 0.0
            self.facing = side
        elif roll < 0.52:
            self._start_walk()
        elif roll < 0.74:
            self._start_jump(events, direction=self.rng.choice((-1, 1)))
        elif roll < 0.88:
            self._start_run()
        else:
            self._idle_left = self.rng.uniform(1.2, 3.0)
            self.state_time = 0.0

    def _start_walk(self) -> None:
        target = self._pick_target(self.tuning.walk_span)
        self._target_x = target
        self.state = State.WALK
        self.state_time = 0.0

    def _start_run(self) -> None:
        target = self._pick_target(self.tuning.run_span)
        self._target_x = target
        self.state = State.RUN
        self.state_time = 0.0

    def _pick_target(self, span: float) -> float:
        margin = self.tuning.edge_margin
        direction = self.rng.choice((-1, 1))
        target = self.world.clamp_x(self.x + direction * self.rng.uniform(90.0, span), margin)
        if abs(target - self.x) < 60.0:
            target = self.world.clamp_x(
                self.x - direction * self.rng.uniform(90.0, span), margin
            )
        return target

    def _start_jump(
        self, events: list[Event], direction: int = 1, boost: float = 1.0
    ) -> None:
        self.vy = -self.tuning.jump_velocity * boost * self.rng.uniform(0.92, 1.08)
        self.vx = direction * self.rng.uniform(40.0, 120.0) * self.speed_scale
        self.facing = 1 if direction >= 0 else -1
        self.state = State.AIR
        self.state_time = 0.0
        events.append(Event.JUMP)

    def _to_idle(self) -> None:
        self.state = State.IDLE
        self.state_time = 0.0
        self.vx = 0.0
        self._idle_left = self.rng.uniform(self.tuning.min_idle, self.tuning.max_idle)

    def _wake(self) -> None:
        self._idle_since_interaction = 0.0
        self._to_idle()

    # ------------------------------------------------------------- cosmetics
    def _update_blink(self, dt: float) -> None:
        if self.state is State.SLEEP:
            self.blink = 1.0
            return
        if self._blink_phase > 0.0:
            self._blink_phase = max(0.0, self._blink_phase - dt)
            progress = 1.0 - (self._blink_phase / BLINK_DURATION)
            self.blink = math.sin(math.pi * progress)
        else:
            self.blink = max(0.0, self.blink - dt * 6.0)
            self._blink_countdown -= dt
            if self._blink_countdown <= 0.0:
                self._blink_phase = BLINK_DURATION
                self._blink_countdown = self.rng.uniform(1.8, 5.0)

    def _update_gaze(self, dt: float) -> None:
        if self.cursor is None:
            target = (0.0, 0.0)
        else:
            head_x, head_y = self.head_position()
            dx = self.cursor[0] - head_x
            dy = self.cursor[1] - head_y
            distance = math.hypot(dx, dy)
            if distance < 1.0:
                target = (0.0, 0.0)
            else:
                reach = min(1.0, distance / 240.0)
                target = (dx / distance * reach, dy / distance * reach)
        blend = min(1.0, dt * 7.0)
        self.look = (
            _lerp(self.look[0], target[0], blend),
            _lerp(self.look[1], target[1], blend),
        )

    def _update_cursor_interest(self, dt: float) -> None:
        if self.cursor is not None and self._cursor_near(self.tuning.cursor_radius):
            if self.state in (State.IDLE, State.WALK, State.RUN):
                self._cursor_dwell += dt
                return
        self._cursor_dwell = 0.0

    def _cursor_near(self, radius: float) -> bool:
        if self.cursor is None:
            return False
        head_x, head_y = self.head_position()
        return math.hypot(self.cursor[0] - head_x, self.cursor[1] - head_y) <= radius
