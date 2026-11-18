# 仿真控制策略节点

[English](README.md) | [简体中文](README_zh.md)

## BREAKING CHANGE：Forge 2.x / Dora 1.x 迁移

本次从 Forge 1.x / Dora 0.4.x 升级需要协同部署。节点对接前必须对齐 Forge 包、Dora CLI/coordinator/daemon、本节点及上下游节点的版本；不支持在 Forge 1.x 部署中只替换单个节点。可执行产物也需要使用匹配环境重新构建和部署。仍使用旧技术栈的部署请保留在 `stable/1.x`。

本轮验证的 Python 基线为 `forge-msgs==2.1.0`、`Pillow==13.0.0`、`forge-common==2.1.0`、按需使用的 `forge-robot` / `forge-policy` / `forge-kinematics` / `forge-tool` 为 `2.0.0`，以及 `dora-rs==1.0.1`。同时遵守本仓库的 Python 和 SDK 平台要求。Forge 各包族独立发布，无需强行使用同一个版本号。Rust 节点继续使用已发布的 `forge_msgs` crate `2.0.0` 和 Dora `1.0.1`；Python Msgs `2.1.0` 不要求升级到尚未发布的 Rust `2.1.0`。消息命名空间 `forge_msgs.v1` 保持不变。

这里的 breaking change 指旧技术栈的部署迁移，不代表真机、真实模型或长时间运行已完成验收。实际测试和未完成项见[本轮验证报告](migration/msgs-2.1.0-report.json)。

独立 Forge Tool 策略节点，为 `robot-control-sim` 提供仿真场景控制：
在 `sim.control` Endpoint 上暴露机器人元数据查询和带延迟归位的场景复位 Action。

## Node、Endpoint 与 Tool API

| 项目 | 当前实现 |
| --- | --- |
| 生产 Node | 1：`sim_control_policy`；源码命令 `forge-sim-control-policy`，打包入口 `dist/sim_control_policy` |
| Tool 接入方式 | Dora `ToolMessage` provider；通过 Gateway 暴露调用入口 |
| 直接 HTTP Tool API | 0；本 Node 不监听 HTTP，调用地址属于 Gateway |
| Endpoint 数 | 1：`sim.control` |
| operation 数 | 2：`get_robot_info`（Query）、`reset`（Action，不可取消、可查状态；各自最大并发 1） |
| Gateway Tool 数 | 由 `tools.specs` 决定；robot-control-sim 为本 Endpoint 配置 2 个 Tool，见下表 |

| Tool ID（robot-control-sim 配置） | Endpoint / operation | provider Node |
| --- | --- | --- |
| `sim.get_robot_info` | `sim.control / get_robot_info` | `sim_control_policy` |
| `sim.reset` | `sim.control / reset` | `sim_control_policy` |

`reset` 经 `sim_command` 复位场景；配置 re-home 时，本 Node 同时作为 Tool caller，
经 `tool_request/tool_response` 调用 Gateway 中已配置的 Motion/Gripper Tool。
这些被调用的 operation 属于其他 provider，不能计入本仓库的 Endpoint/operation 数。
ToolSpec 的 `implementation_id` 是部署绑定标识，可不同于包名或 Node ID；以实际 profile 为准。

完整契约见 [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md)，descriptor 见
[info.py](src/sim_control_policy_node/info.py)，reset 编排见
[control.py](src/sim_control_policy_node/control.py)。

兼容性：当前依赖声明为 `dora-rs>=1.0.1,<2`、`forge-msgs>=2.0.0,<3`；以 [pyproject.toml](pyproject.toml) 与 [uv.lock](uv.lock) 为准。 Tool 协议实现来自正式 `forge-tool[dora]` 分发包。 这些声明不构成跨版本互操作保证；使用制品时还需核对 build revision 和 Skill lock。

后续修改 Node 入口、Endpoint 或 Tool API 时，请同步更新本节及对应配置/契约，遵循 [Node README 规范](https://github.com/PhyAgentOS/forge/blob/master/CONTRIBUTING.md#node-readme-contract)。

## Tool 契约

| tool_id | implementation_id | endpoint_id | operation | 语义 |
| --- | --- | --- | --- | --- |
| `sim.get_robot_info` | `sim-control-policy` | `sim.control` | `get_robot_info` | query |
| `sim.reset` | `sim-control-policy` | `sim.control` | `reset` | action |

完整请求/响应、幂等性和错误码见 [`TOOL_CONTRACTS.md`](TOOL_CONTRACTS.md)。

## 设计目的

`move-arm-by-ee` 的运行链（gateway → motion policies → motion server → controllers → mujoco）
已经支持关节值与末端位姿运动。本仓库补充两项仿真控制能力，无需修改其他运行时节点：

- `get_robot_info`（Query）：返回校验后的机器人描述，包含关节名称/顺序、自由度、类型/限制、
  末端 site 和初始位姿，使 Agent 在运行时发现内置或用户提供的机器人，而非解析 SKILL.md。
- `reset`（Action）：经 `sim_command` 发送 `reset_scene`，并将机器人归位到 descriptor 的 `initial_qpos`。
  归位经 Gateway 公共调用通道完成：等待 `settle_ms` 后调用 `move_joints`/`set_opening`，
  聚合完成状态后才结束外层调用。因此归位模式下 `sim.reset` 的终态意味着场景和机器人都已回到初始状态，
  不会被 JTC 保持命令再次拉回。profile 不含 `reset:` 配置时，场景复位后即完成。

机器人差异通过声明配置表达；本节点读取 MJCF/URDF 资产旁的 `robot.yaml`，
增加同契约机器人无需修改本节点源码。

## 配置

```yaml
# profiles/<profile>/sim_control_policy.yaml
robot_descriptor_path: ../../robots/piper/robot.yaml  # relative to this file

# 可选归位阶段；省略时场景复位后即完成。
reset:
  motion:                       # 存在 reset 时必填
    tool_id: sim.set_joint_positions
    implementation_id: motion.integration
    endpoint_id: motion.server
    operation: move_joints
    arguments:
      group_name: piper_arm     # 并配置 velocity_scale / acceleration_scale
  gripper:                      # 可选；没有 Tool 夹爪时省略
    tool_id: sim.set_gripper_opening
    implementation_id: piper.gripper
    endpoint_id: gripper.controller
    operation: set_opening
  timeout_ms: 15000             # 归位总预算，默认值
  poll_interval_ms: 1000        # 结果轮询周期，默认值
  settle_ms: 500                # 运动前等待仿真状态传播，默认值
```

完整 schema 见 `tests/`；配置严格校验，拒绝未知键。

## Dora 接线

| 输入 | 用途 |
| --- | --- |
| `tool_in` | Gateway 发来的调用/注册消息 |
| `tool_response` | 内层归位调用的响应与事件 |
| `tick` | 驱动注册租约和归位计时器 |

| 输出 | 用途 |
| --- | --- |
| `tool_out` | 响应、租约注册/注销 |
| `tool_request` | 经 Gateway 公共调用通道发送内层 Tool 请求 |
| `sim_command` | 发给 MuJoCo 的 UTF-8 JSON `{"command": "reset_scene"}` |

## 开发

```bash
uv sync --frozen --all-groups
uv run pytest -q
uv run ruff check .
scripts/build_pyinstaller.sh   # single-file executable -> dist/sim_control_policy
```

`forge_tool` 由正式 `forge-tool[dora]>=2.0.0,<3` 分发包提供，不再维护仓库内副本。

## 许可证

本仓库使用 Apache License 2.0，详见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 与
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## Forge 2.x 迁移

本分支准备节点版本 `2.0.0`，适配 Dora 1.x，迁移验证锁定 Dora `1.0.1`。使用正式 Forge 2.x 分发包；Common 至少为 `2.1.0`。此次更新包括依赖锁文件与各独立可执行入口。

每轮报告必须列出仓库、改动和测试证据，包括各节点的 `dora run` 记录，以及包含 `adapter-forge-gateway` 的串联测试。缺少硬件或模型的验收项保持待验证。源码 PR 不等于正式发布；整体验收通过后再同步 GitLab。

## 分版本发布

| 维护线 | 源码 | 节点/包版本 | 运行时 |
| --- | --- | --- | --- |
| Forge 1.x | `stable/1.x` | `1.x`，标签 `v1.X.Y` | Forge 1.x / Dora 0.4.x |
| Forge 2.x | `master` | `2.x`，标签 `v2.X.Y` | Forge 2.x / Dora 1.x |

**旧版版本号统一：** `stable/1.x` 原为 0.x 的节点以 **1.0.0** 发布，保留 Forge 1.x / Dora 0.4.x 依赖与运行行为。已有 1.x 版本保留。节点/包主版本与 Forge 兼容线一致，不再接受 0.x 发布标签。

两条线均从 `master` 运行 **Build versioned release**。先将版本和锁文件修改通过 PR 合并至对应源码分支，再在已审查提交上创建未占用的 **annotated** 标签，标签必须匹配包元数据。禁止移动已有标签或复用已发布版本。工作流使用自身已审查的发布工具与精确标签源码，旧标签无需包含新发布脚本。

```bash
# 替换为已存在、已审查、未发布且与源码元数据一致的标签。
TAG=v1.X.Y
gh workflow run release.yml --ref master -f release_line=1.x -f tag="$TAG"
TAG=v2.X.Y
gh workflow run release.yml --ref master -f release_line=2.x -f tag="$TAG"
```

流水线校验标签类型、源码提交、分支归属、源码版本及锁定的 Forge/Dora 兼容性；构建源码归档及项目支持的 wheel/sdist，检查 Python 分发元数据与 SHA-256，并创建或附加至 **GitHub Release 草稿**。不覆盖已发布 Release 或产物；发布前检查全部构建结果与验收依据。该流程不发布节点包至 PyPI。

设置 `build_binaries=true` 复用已有 Ubuntu 20.04 二进制工作流，保留原架构、CLI 和归档校验。也可直接运行 `build-ubuntu20.yml`，传入 `ref`、`version`、`release_line`；`ref` 必须为 annotated 标签，不能为移动分支。仅在所有选定任务通过后附加二进制产物。

源码归档保留标签中的文件；外部 SDK/submodule、模型下载与现场配置仍是独立前置条件。依赖或 SDK 构建失败不能视为发布验收通过。构建成功不代表单节点或串联 `dora run`、真机、真实模型、长稳态或回滚验收通过；每条验收链必须包含相同兼容线的 `adapter-forge-gateway`。Forge 2.x 属于 **breaking change**，整个部署的 Forge 库、节点版本与 Dora 必须对齐；1.x 保留在维护分支。
