"""Latest joint observation cached for the ``get_joint_state`` query.

The simulator publishes ``JointState`` on ``mujoco/proprio_state``. This module
keeps the newest sample and its arrival timestamp so a query can tell a fresh
observation from a stale or never-received one instead of reporting an arm pose
that no longer describes the plant.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from forge_msgs import JointState


@dataclass(frozen=True)
class JointStateSample:
    """One cached observation plus the monotonic time it was received."""

    state: JointState
    received_ns: int

    def to_outputs(self, *, age_ms: float) -> dict[str, Any]:
        """Payload of the ``get_joint_state`` query operation."""
        return {
            "name": list(self.state.name),
            "position": list(self.state.position),
            "velocity": list(self.state.velocity),
            "effort": list(self.state.effort),
            "age_ms": age_ms,
        }


class JointStateCache:
    """Bounded, dependency-free cache of the newest ``JointState``."""

    def __init__(
        self,
        *,
        timeout_ms: int = 200,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise ValueError("joint_state_timeout_ms must be a positive integer")
        self.timeout_ns = timeout_ms * 1_000_000
        self._clock_ns = clock_ns
        self._sample: JointStateSample | None = None

    def update(self, state: JointState, *, now_ns: int | None = None) -> None:
        self._sample = JointStateSample(
            state=state,
            received_ns=self._clock_ns() if now_ns is None else now_ns,
        )

    @property
    def sample(self) -> JointStateSample | None:
        return self._sample

    def fresh(self, *, now_ns: int | None = None) -> JointStateSample | None:
        """Return the cached sample, or ``None`` when it is older than the timeout."""
        sample = self._sample
        if sample is None:
            return None
        current_ns = self._clock_ns() if now_ns is None else now_ns
        if current_ns - sample.received_ns > self.timeout_ns:
            return None
        return sample

    def age_ms(self, *, now_ns: int | None = None) -> float | None:
        sample = self._sample
        if sample is None:
            return None
        current_ns = self._clock_ns() if now_ns is None else now_ns
        return max(0.0, (current_ns - sample.received_ns) / 1_000_000)


__all__ = ["JointStateCache", "JointStateSample"]
