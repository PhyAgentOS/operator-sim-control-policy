from __future__ import annotations

import asyncio

import pytest
from forge_msgs import JointState

from forge_tool import ToolContext, ToolEndpointError, ToolExecutionKey, ToolRequest
from sim_control_policy_node.info import (
    INFO_OPERATION,
    RESET_OPERATION,
    SIM_CONTROL_DESCRIPTOR,
    STATE_OPERATION,
    SimInfoEndpoint,
)
from sim_control_policy_node.robot_descriptor import JointDescriptor, RobotDescriptor
from sim_control_policy_node.state import JointStateCache


def _descriptor() -> RobotDescriptor:
    return RobotDescriptor(
        name="piper",
        source="mjcf",
        model="piper_mujoco/scene.xml",
        joints=(
            JointDescriptor("joint1", "revolute", (-1.0, 1.0)),
            JointDescriptor("gripper", "prismatic", (0.0, 0.02)),
        ),
        eef_site="tcp",
        initial_qpos={"joint1": 0.0},
        has_gripper=True,
        notes="test arm",
    )


def _context(*, operation: str = INFO_OPERATION, deadline_ms: int | None = None) -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey("invoke-1", "attempt-1"),
        tool_id="sim.get_robot_info",
        implementation_id="sim-control-policy",
        endpoint_id="sim.control",
        operation=operation,
        deadline_ms=deadline_ms,
    )


def test_descriptor_declares_every_operation() -> None:
    assert SIM_CONTROL_DESCRIPTOR.endpoint_id == "sim.control"
    assert [
        (item.name, item.semantics, item.cancellable, item.status_supported)
        for item in SIM_CONTROL_DESCRIPTOR.operations
    ] == [
        ("get_robot_info", "query", False, False),
        ("get_joint_state", "query", False, False),
        ("reset", "action", False, True),
    ]


def test_query_returns_descriptor_info() -> None:
    endpoint = SimInfoEndpoint(_descriptor())

    result = asyncio.run(endpoint.query(ToolRequest({}), _context()))

    assert result.status == "succeeded"
    assert result.outputs["name"] == "piper"
    assert result.outputs["dof"] == 2
    assert result.outputs["joints"][0] == {
        "name": "joint1",
        "kind": "revolute",
        "unit": "radians",
        "limits": [-1.0, 1.0],
    }
    assert result.outputs["eef_site"] == "tcp"
    assert result.outputs["has_gripper"] is True


def test_query_rejects_wrong_operation() -> None:
    endpoint = SimInfoEndpoint(_descriptor())
    with pytest.raises(ToolEndpointError):
        asyncio.run(endpoint.query(ToolRequest({}), _context(operation=RESET_OPERATION)))


def test_query_rejects_expired_deadline() -> None:
    endpoint = SimInfoEndpoint(_descriptor(), epoch_ms=lambda: 5_000)
    with pytest.raises(ToolEndpointError):
        asyncio.run(endpoint.query(ToolRequest({}), _context(deadline_ms=4_000)))


def test_query_rejects_arguments() -> None:
    endpoint = SimInfoEndpoint(_descriptor())
    with pytest.raises(ToolEndpointError):
        asyncio.run(endpoint.query(ToolRequest({"robot": "piper"}), _context()))


def test_joint_state_query_returns_the_cached_sample() -> None:
    cache = JointStateCache(timeout_ms=200, clock_ns=lambda: 1_000_000_000)
    cache.update(
        JointState(
            name=["joint1", "joint2"],
            position=[0.1, 0.2],
            velocity=[0.01, 0.02],
            effort=[],
        ),
        now_ns=900_000_000,
    )
    endpoint = SimInfoEndpoint(_descriptor(), joint_state=cache)

    result = asyncio.run(
        endpoint.query(ToolRequest({}), _context(operation=STATE_OPERATION))
    )

    assert result.status == "succeeded"
    assert result.outputs["name"] == ["joint1", "joint2"]
    assert result.outputs["position"] == [0.1, 0.2]
    assert result.outputs["velocity"] == [0.01, 0.02]
    assert result.outputs["age_ms"] == pytest.approx(100.0)


def test_joint_state_query_rejects_a_stale_sample() -> None:
    cache = JointStateCache(timeout_ms=50, clock_ns=lambda: 1_000_000_000)
    cache.update(JointState(name=["joint1"], position=[0.1]), now_ns=900_000_000)
    endpoint = SimInfoEndpoint(_descriptor(), joint_state=cache)

    with pytest.raises(ToolEndpointError) as error:
        asyncio.run(endpoint.query(ToolRequest({}), _context(operation=STATE_OPERATION)))

    assert error.value.error.code == "NO_FRESH_ROBOT_STATE"


def test_joint_state_query_without_any_sample_is_not_fresh() -> None:
    endpoint = SimInfoEndpoint(
        _descriptor(),
        joint_state=JointStateCache(timeout_ms=200, clock_ns=lambda: 0),
    )

    with pytest.raises(ToolEndpointError) as error:
        asyncio.run(endpoint.query(ToolRequest({}), _context(operation=STATE_OPERATION)))

    assert error.value.error.code == "NO_FRESH_ROBOT_STATE"
