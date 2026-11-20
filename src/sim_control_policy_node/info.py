"""Forge Query endpoint: robot metadata for simulation skills.

``get_robot_info`` returns the validated robot descriptor (joint order, dof,
per-joint kind/limits, EEF site, initial pose) so agents can discover any
bundled or user-supplied robot at runtime, without reading SKILL.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolContext,
    ToolEndpointDescriptor,
    ToolEndpointError,
    ToolError,
    ToolOperationDescriptor,
    ToolRequest,
    ToolResult,
)

from .robot_descriptor import RobotDescriptor
from .state import JointStateCache

ENDPOINT_ID = "sim.control"
INFO_OPERATION = "get_robot_info"
STATE_OPERATION = "get_joint_state"
RESET_OPERATION = "reset"

SIM_CONTROL_DESCRIPTOR = ToolEndpointDescriptor(
    protocol_version=TOOL_ENDPOINT_PROTOCOL,
    endpoint_id=ENDPOINT_ID,
    operations=(
        ToolOperationDescriptor(
            name=INFO_OPERATION,
            semantics="query",
            max_concurrency=1,
        ),
        ToolOperationDescriptor(
            name=STATE_OPERATION,
            semantics="query",
            max_concurrency=1,
        ),
        ToolOperationDescriptor(
            name=RESET_OPERATION,
            semantics="action",
            cancellable=False,
            status_supported=True,
            max_concurrency=1,
        ),
    ),
)


def _error(code: str, message: str) -> ToolEndpointError:
    return ToolEndpointError(ToolError(code=code, message=message))


class SimInfoEndpoint:
    """Query SPI adapter over a loaded robot descriptor and the joint state cache."""

    def __init__(
        self,
        descriptor: RobotDescriptor,
        *,
        joint_state: JointStateCache | None = None,
        epoch_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self.descriptor = descriptor
        self._joint_state = joint_state
        self._epoch_ms = epoch_ms

    async def query(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        if context.operation not in {INFO_OPERATION, STATE_OPERATION}:
            raise _error(
                "FORGE_PROTOCOL_UNKNOWN_OPERATION",
                f"unknown operation {context.operation!r}",
            )
        if context.deadline_ms is not None and self._epoch_ms() >= context.deadline_ms:
            raise _error("FORGE_DEADLINE_EXCEEDED", "the Tool invocation deadline has expired")
        if request.arguments:
            raise _error(
                "SIM_INVALID_ARGUMENT",
                f"{context.operation} takes no arguments",
            )
        if context.operation == STATE_OPERATION:
            if self._joint_state is None:
                raise _error(
                    "NO_FRESH_ROBOT_STATE",
                    "no joint state input is wired on this node",
                )
            sample = self._joint_state.fresh()
            if sample is None:
                age_ms = self._joint_state.age_ms()
                raise _error(
                    "NO_FRESH_ROBOT_STATE",
                    "no fresh JointState arrived within joint_state_timeout_ms"
                    + (f" (last sample {age_ms:.1f} ms ago)" if age_ms is not None else ""),
                )
            return ToolResult(
                status="succeeded",
                outputs=sample.to_outputs(age_ms=self._joint_state.age_ms() or 0.0),
            )
        info: dict[str, Any] = self.descriptor.to_info_json()
        return ToolResult(status="succeeded", outputs=info)
