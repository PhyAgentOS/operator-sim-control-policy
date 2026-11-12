# Sim Control Policy Node

[English](README.md) | [简体中文](README_zh.md)

## BREAKING CHANGE: Forge 2.x / Dora 1.x migration

This migration from Forge 1.x / Dora 0.4.x requires coordinated deployment. Align the Forge packages, Dora CLI/coordinator/daemon, this node and its peer nodes before connecting a dataflow; replacing only one node in a Forge 1.x deployment is unsupported. Rebuild and redeploy executable artifacts with the matching environment. Keep `stable/1.x` for deployments that still use the previous stack.

The validated Python baseline is `forge-msgs==2.1.0`, `Pillow==13.0.0`, `forge-common==2.1.0`, the applicable `forge-robot` / `forge-policy` / `forge-kinematics` / `forge-tool` packages at `2.0.0`, and `dora-rs==1.0.1`. Respect this repository's Python and SDK platform requirements. Forge package families have independent versions. Rust nodes retain the published `forge_msgs` crate `2.0.0` with Dora `1.0.1`; Python Msgs `2.1.0` does not require a nonexistent Rust `2.1.0` release. The `forge_msgs.v1` message namespace remains unchanged.

This notice describes the deployment break from the previous stack; it does not declare hardware, real-model or sustained-run acceptance complete. See [this round's verification report](migration/msgs-2.1.0-report.json) for actual tests and outstanding gates.

Standalone Forge Tool policy node that exposes simulation-scene control for the
`robot-control-sim` skill: a **robot metadata query** and a **scene reset
action with deferred re-home** on the `sim.control` endpoint.

## Node, Endpoint and Tool API

| Item | Current implementation |
| --- | --- |
| Production Nodes | 1: `sim_control_policy`; source command `forge-sim-control-policy`, packaged entrypoint `dist/sim_control_policy` |
| Tool integration | Dora `ToolMessage` provider; caller-facing access through Gateway |
| Direct HTTP Tool API | 0; this Node does not listen on HTTP; Gateway owns the invocation URL |
| Endpoints | 1: `sim.control` |
| Operations | 2: `get_robot_info` (Query), `reset` (Action, not cancellable, status supported; each has maximum concurrency 1) |
| Gateway Tools | Deployment-defined in `tools.specs`; robot-control-sim binds 2 Tools to this Endpoint, listed below |

| Tool ID (robot-control-sim configuration) | Endpoint / operation | Provider Node |
| --- | --- | --- |
| `sim.get_robot_info` | `sim.control / get_robot_info` | `sim_control_policy` |
| `sim.reset` | `sim.control / reset` | `sim_control_policy` |

`reset` resets the scene through `sim_command`. With re-home configured, this Node is also a Tool caller:
it invokes Gateway-configured Motion/Gripper Tools over `tool_request/tool_response`.
Those operations belong to other providers and are excluded from this repository's Endpoint/operation counts.
ToolSpec `implementation_id` is a deployment binding identifier and may differ from the package or Node name; use the actual profile.

Complete contract: [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md). Descriptor:
[info.py](src/sim_control_policy_node/info.py). Reset orchestration:
[control.py](src/sim_control_policy_node/control.py).

Compatibility: current dependency declarations are `dora-rs>=1.0.1,<2`, `forge-msgs>=2.0.0,<3`. See [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock). The Tool protocol implementation comes from the official `forge-tool[dora]` distribution. These declarations do not guarantee cross-version interoperability; also check the build revision and Skill lock when using artifacts.

Changes to Node entrypoints, Endpoints or Tool APIs must update this section and the associated configuration/contracts. Follow the [Node README contract](https://github.com/PhyAgentOS/forge/blob/master/CONTRIBUTING.md#node-readme-contract).

## Tool contracts

| tool_id | implementation_id | endpoint_id | operation | semantics |
| --- | --- | --- | --- | --- |
| `sim.get_robot_info` | `sim-control-policy` | `sim.control` | `get_robot_info` | query |
| `sim.reset` | `sim-control-policy` | `sim.control` | `reset` | action |

Full request/response shapes, idempotency, and error codes are specified in
[`TOOL_CONTRACTS.md`](TOOL_CONTRACTS.md).

## Why

The `move-arm-by-ee` runtime chain (gateway → motion policies → motion server →
controllers → mujoco) already moves the simulated arm by joint values or by EEF
pose. Two things were missing for a simulation-control skill, and both live here
so that no other runtime node needs to change:

- **`get_robot_info` (query)** — returns the validated robot descriptor
  (joint names/order, dof, per-joint kind/limits, EEF site, initial pose) so
  agents can discover any bundled or user-supplied robot at runtime instead of
  parsing SKILL.md.
- **`reset` (action)** — resets the MuJoCo scene (`reset_scene` over
  `sim_command`) **and re-homes the robot** to the descriptor's `initial_qpos`.
  The re-home rides the gateway's public caller channel: after a `settle_ms`
  window the node dispatches inner `move_joints`/`set_opening` Tool invokes,
  aggregates their completion, and only then completes the outer invoke — so a
  terminal `sim.reset` result means the scene *and* the robot are actually at
  the initial state (the JTC hold tick can no longer drag the arm back). When
  the profile has no `reset:` block the invoke completes immediately after the
  scene reset.

Robot variation is entirely declarative: the node only reads a `robot.yaml`
descriptor next to the robot's MJCF/URDF assets. Adding a robot never requires
code changes here.

## Configuration

```yaml
# profiles/<profile>/sim_control_policy.yaml
robot_descriptor_path: ../../robots/piper/robot.yaml  # relative to this file

# Optional re-home stage; omit for instant completion after the scene reset.
reset:
  motion:                       # mandatory when reset is present
    tool_id: sim.set_joint_positions
    implementation_id: motion.integration
    endpoint_id: motion.server
    operation: move_joints
    arguments:
      group_name: piper_arm     # plus velocity_scale / acceleration_scale
  gripper:                      # optional; omit for arms without a Tool-driven gripper
    tool_id: sim.set_gripper_opening
    implementation_id: piper.gripper
    endpoint_id: gripper.controller
    operation: set_opening
  timeout_ms: 15000             # re-home budget (default)
  poll_interval_ms: 1000        # result-lookup cadence (default)
  settle_ms: 500                # simulator propagation window before motion (default)
```

See `tests/` for the full schema (validated strictly; unknown keys are
rejected).

## Dora wiring

| input          | purpose                                               |
| -------------- | ----------------------------------------------------- |
| `tool_in`      | Tool envelopes from the gateway (invoke/registry)     |
| `tool_response`| gateway replies/events for the inner re-home invokes  |
| `tick`         | keeps the registration lease and re-home timers driven |

| output        | purpose                                                   |
| ------------- | --------------------------------------------------------- |
| `tool_out`    | responses, lease registration/unregister envelopes        |
| `tool_request`| inner Tool invokes on the gateway caller channel          |
| `sim_command` | raw UTF-8 JSON `{"command": "reset_scene"}` to mujoco     |

## Development

```bash
uv sync --frozen --all-groups
uv run pytest -q
uv run ruff check .
scripts/build_pyinstaller.sh   # single-file executable -> dist/sim_control_policy
```

The `forge_tool` package is vendored under `src/forge_tool/`;
`sim_control_policy_node/__init__.py` prepends it to `sys.path` (defensively,
also under PyInstaller). Keep it byte-identical to the copy in the other policy
nodes.

## License

Apache License 2.0 — see [LICENSE](LICENSE), [NOTICE](NOTICE), and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Forge 2.x migration

This branch prepares node version `2.0.0` for Dora 1.x, frozen to Dora `1.0.1` for migration validation. It uses the official Forge 2.x distributions; Common is at least `2.1.0`. Regenerated locks and all executable entrypoints are part of the change.

Every change report must list repository, changes and test evidence, including per-node `dora run` records and a chained test containing `adapter-forge-gateway`. Unavailable hardware/model checks remain pending. Source PRs do not publish stable releases or synchronize GitLab; synchronization follows full acceptance.

ToolEndpoint implementations now come from `forge-tool[dora]>=2.0.0,<3`. The former repository-local Tool copy and private message imports are removed; messages use the public `forge_msgs.ToolMessage`.
