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
    DANCE = "dance"
    CLIMB = "climb"


class Event(str, Enum):
    JUMP = "jump"
    LAND = "land"
    WAKE = "wake"
    POKE = "poke"
    DANCE = "dance"
    PERCH = "perch"
    DROP = "drop"


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


@dataclass(frozen=True)
class Perch:
    """A place to hang out: the top edge of somebody else's window."""

    x: float
    y: float
    left: float
    right: float
    kind: str = "window"

    def matches(self, other: "Perch", tolerance: float = 6.0) -> bool:
        return (
            abs(self.x - other.x) <= tolerance
            and abs(self.y - other.y) <= tolerance
            and abs(self.left - other.left) <= tolerance
            and abs(self.right - other.right) <= tolerance
        )


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
    climb_speed: float = 195.0
    dance_min: float = 2.6
    dance_max: float = 4.4


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
    can_dance: bool = False
    reduced_motion: bool = False
    gravity_scale: float = 1.0
    max_fall_speed: float = 1500.0
    jump_scale: float = 1.0
    body_height: float = 90.0

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
    screen_world: World | None = None
    perch: Perch | None = None
    perched: bool = False
    dance_left: float = 0.0
    focus_kind: str = ""
    focus_status: str = "stopped"

    _blink_countdown: float = 2.0
    _blink_phase: float = 0.0
    _idle_left: float = 1.0
    _target_x: float = 0.0
    _idle_since_interaction: float = 0.0
    _cursor_dwell: float = 0.0
    _drag_samples: list[tuple[float, float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.screen_world is None:
            self.screen_world = self.world
        if self.y == 0.0:
            self.y = self.world.ground
        if self.x == 0.0:
            self.x = (self.world.left + self.world.right) / 2.0

    # ------------------------------------------------------------- geometry
    @property
    def height(self) -> float:
        """Height above the current floor (0 when standing/walking on it)."""
        return max(0.0, self.world.ground - self.y)

    @property
    def airborne(self) -> bool:
        return self.state is State.AIR

    @property
    def grounded(self) -> bool:
        return self.state not in (State.AIR, State.DRAG, State.CLIMB)

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
        """Double-click interaction: dance when supported, otherwise happy hop."""
        events: list[Event] = [Event.POKE]
        self.note_interaction()
        if self.reduced_motion:
            return events
        if self.state not in (State.AIR, State.DRAG, State.CLIMB, State.DANCE):
            if self.can_dance:
                events.extend(self.dance())
            else:
                self._start_jump(events, direction=self.facing or 1, boost=1.2)
        return events

    def dance(self) -> list[Event]:
        """Start a little dance party."""
        self.note_interaction()
        if self.reduced_motion:
            return []
        if self.state in (State.AIR, State.DRAG, State.CLIMB):
            return []
        if self.state is State.DANCE:
            self.dance_left = max(self.dance_left, self.rng.uniform(2.0, 3.0))
            return []
        self.state = State.DANCE
        self.state_time = 0.0
        self.dance_left = self.rng.uniform(self.tuning.dance_min, self.tuning.dance_max)
        self.vx = 0.0
        self.vy = 0.0
        return [Event.DANCE]

    def start_drag(self) -> None:
        self.note_interaction()
        self.perch = None
        self.perched = False
        self.world = self.screen_world or self.world
        self.state = State.DRAG
        self.state_time = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self._drag_samples = []

    def drag_to(self, x: float, y: float, now: float = 0.0) -> None:
        screen = self.screen_world or self.world
        margin = self.tuning.edge_margin
        self.x = screen.clamp_x(x, margin)
        self.y = max(screen.ceiling + self.body_height + 2.0, min(screen.ground, y))
        self._drag_samples.append((now, self.x, self.y))
        if len(self._drag_samples) > 5:
            self._drag_samples.pop(0)

    def end_drag(self, vx: float = 0.0, vy: float = 0.0) -> None:
        self.vx = max(-1200.0, min(1200.0, vx))
        self.vy = max(-1400.0, min(1400.0, vy))
        screen = self.screen_world or self.world
        self.world = screen
        if self.y < screen.ground - 4.0 or abs(self.vy) > 140.0:
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

    # ------------------------------------------------------------------ perch
    def set_perch(self, perch: Perch) -> bool:
        """Climb up to (or follow) a window's top edge. True when started."""
        if self.state is State.DRAG:
            return False
        if (
            self.perch is not None
            and self.perch.matches(perch)
            and (self.perched or self.state is State.CLIMB)
        ):
            return False
        screen = self.screen_world or self.world
        self.perch = perch
        self.perched = False
        self.world = World(
            left=perch.left,
            right=perch.right,
            ground=perch.y,
            ceiling=screen.ceiling,
        )
        self.state = State.CLIMB
        self.state_time = 0.0
        self.vx = 0.0
        self.vy = 0.0
        return True

    def clear_perch(self) -> list[Event]:
        """Let go of the perch and fall/float back to the screen floor."""
        if (
            self.perch is None
            and not self.perched
            and self.world is (self.screen_world or self.world)
        ):
            return []
        self.perch = None
        self.perched = False
        self.world = self.screen_world or self.world
        self.vx *= 0.35
        self.vy = max(self.vy, 40.0)
        if self.state is not State.DRAG:
            self.state = State.AIR
            self.state_time = 0.0
        return [Event.DROP]

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
            if (
                self._cursor_near(self.tuning.wake_radius)
                or self._idle_since_interaction < 0.25
            ):
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
        elif state is State.DANCE:
            if self.state_time >= self.dance_left:
                self._to_idle()
        elif state is State.CLIMB:
            self._step_climb(dt, events)
        return events

    # --------------------------------------------------------------- internals
    def _step_air(self, dt: float, events: list[Event]) -> None:
        self.vy += self.tuning.gravity * self.gravity_scale * dt
        self.vy = min(self.max_fall_speed, self.vy)
        if self.gravity_scale < 0.8:
            # ghosts drift dreamily while falling
            self.vx += math.sin(self.anim_time * 2.4) * 14.0 * dt
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
        if self.y >= self.world.ground and self.vy >= 0.0:
            self.last_impact = self.vy
            self.y = self.world.ground
            self.vx = 0.0
            self.vy = 0.0
            self.state = State.LAND
            self.state_time = 0.0
            events.append(Event.LAND)
        elif self.y < self.world.ceiling + self.body_height * 0.6:
            self.y = self.world.ceiling + self.body_height * 0.6
            self.vy = abs(self.vy) * 0.5

    def _step_climb(self, dt: float, events: list[Event]) -> None:
        perch = self.perch
        if perch is None:
            self._to_idle()
            return
        dx = perch.x - self.x
        dy = perch.y - self.y
        distance = math.hypot(dx, dy)
        speed = self.tuning.climb_speed * max(0.6, self.speed_scale)
        if distance <= max(3.0, speed * dt):
            self.x = perch.x
            self.y = perch.y
            self.vx = self.vy = 0.0
            self.perched = True
            self.state = State.LAND
            self.state_time = 0.0
            events.append(Event.PERCH)
            return
        ratio = speed * dt / distance
        self.x += dx * ratio
        self.y += dy * ratio
        self.x += math.sin(self.anim_time * 9.0) * 10.0 * dt
        self.facing = 1 if dx >= 0 else -1
        self.x = self.world.clamp_x(self.x, min(20.0, self.tuning.edge_margin))
        self.y = min(self.world.ground, max(self.world.ceiling, self.y))

    def _step_walk(self, dt: float, events: list[Event]) -> None:
        speed = (
            self.tuning.run_speed if self.state is State.RUN else self.tuning.walk_speed
        )
        speed *= self.speed_scale
        direction = 1 if self._target_x >= self.x else -1
        self.facing = direction
        self.vx = direction * speed
        self.x += self.vx * dt
        distance = abs(self.x - self._target_x)
        if distance <= max(2.5, speed * dt):
            self.x = self._target_x
            self._to_idle()
        elif not self.reduced_motion and self.rng.random() < 0.13 * dt:
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

        curious = (
            not self.reduced_motion
            and self.playful
            and self.cursor is not None
            and self._cursor_dwell > 1.0
            and self._cursor_near(self.tuning.cursor_radius)
            and self.perch is None
        )
        if self.reduced_motion:
            weights: dict[str, float] = {"walk": 35.0, "linger": 65.0}
        else:
            weights = {
                "walk": 40.0,
                "jump": 20.0,
                "run": 12.0,
                "linger": 12.0,
            }
        if self.can_dance and not self.reduced_motion:
            weights["dance"] = 16.0
        if curious:
            weights = {"chase": 55.0, "jump": 15.0, "linger": 15.0}
            if self.can_dance:
                weights["dance"] = 15.0
        names = list(weights)
        choice = self.rng.choices(names, weights=list(weights.values()), k=1)[0]

        if choice == "chase":
            cursor_x = self.cursor[0]  # type: ignore[index]
            side = 1 if self.x < cursor_x else -1
            self._target_x = self.world.clamp_x(
                cursor_x - side * 70.0, self.tuning.edge_margin
            )
            self.state = State.RUN
            self.state_time = 0.0
            self.facing = side
        elif choice == "walk":
            self._start_walk()
        elif choice == "jump":
            self._start_jump(events, direction=self.rng.choice((-1, 1)))
        elif choice == "run":
            self._start_run()
        elif choice == "dance":
            events.extend(self.dance())
        else:
            self._idle_left = self.rng.uniform(1.2, 3.0)
            self.state_time = 0.0

    def _start_walk(self) -> None:
        self._target_x = self._pick_target(self.tuning.walk_span)
        self.state = State.WALK
        self.state_time = 0.0

    def _start_run(self) -> None:
        self._target_x = self._pick_target(self.tuning.run_span)
        self.state = State.RUN
        self.state_time = 0.0

    def _pick_target(self, span: float) -> float:
        margin = min(self.tuning.edge_margin, self.world.width / 4.0)
        direction = self.rng.choice((-1, 1))
        target = self.world.clamp_x(
            self.x + direction * self.rng.uniform(90.0, span), margin
        )
        if abs(target - self.x) < 60.0:
            target = self.world.clamp_x(
                self.x - direction * self.rng.uniform(90.0, span), margin
            )
        return target

    def _start_jump(
        self, events: list[Event], direction: int = 1, boost: float = 1.0
    ) -> None:
        self.vy = (
            -self.tuning.jump_velocity
            * boost
            * self.jump_scale
            * self.rng.uniform(0.92, 1.08)
        )
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
