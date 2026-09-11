# 成员2交接记录

## 当前仓库状态

- 仓库：breeze-sys/CRAFT
- 分支：main
- 当前测试环境：conda 环境 `craft`
- Python 版本：3.10.21
- 基础测试结果：`python -m pytest -q --tb=short`
- 测试通过情况：14 passed in 0.12s

## 成员1已完成内容初步判断

根据当前文件结构与测试结果，成员1已完成：

- 项目基础结构：`src/craft/`、`tests/`、`docs/`、`scripts/`
- Python 项目元数据与依赖配置
- 协议基础数据模型
- 序列化相关工具
- 风险策略基础结构
- Grid2Op 数据目录与健康检查相关工具
- Grid2Op smoke checks / dataset tooling 的基础测试

## 成员2接手目标

成员2主要负责电力仿真与风险部分：

- 跑通 Grid2Op 环境
- 读取 Observation
- 支持基础动作，例如 redispatch、disconnect_line、reconnect_line、change_topology
- 实现 Consequence Metrics
- 实现 Risk Engine
- 实现执行前 Revalidation
- 构造两个关键实验场景：
  - 同一动作在两个不同电网状态下得到不同风险等级
  - 审批后状态变化导致风险升级并触发重新授权

## 下一步待办

- 阅读 `src/craft/grid2op_datasets.py`
- 阅读 `src/craft/grid2op_health.py`
- 阅读 `src/craft/models.py`
- 阅读 `src/craft/policy.py`
- 阅读 `tests/test_grid2op_datasets.py`
- 判断当前 Grid2Op 相关代码只是 smoke check，还是已经具备仿真动作能力
- 新增或补充成员2负责的测试记录

## Grid2Op 基础环境测试结果

### 已运行命令

- `make check`
- `make check-full`
- `make check-grid`

### 结果

- `make check`：通过，Python 3.10.21，满足项目要求 `>=3.10,<3.13`
- `make check-full`：通过，fastapi、gmssl、grid2op、numpy、pandas、pydantic、scipy、typer、uvicorn 均可导入
- `make check-grid`：通过，两个 Grid2Op test 环境均可 reset 并执行 noop step

### Grid2Op smoke check 结果

- `l2rpn_case14_sandbox`
  - lines: 20
  - generators: 6
  - loads: 11
  - redispatchable generators: 3
  - max rho: 0.9253
  - done after noop: False

- `educ_case14_redisp`
  - lines: 20
  - generators: 6
  - loads: 11
  - redispatchable generators: 3
  - max rho: 0.8534
  - done after noop: False

### 当前判断

成员1提供的环境、依赖、Grid2Op test 环境 smoke check 已经可用。成员2下一步应从真实数据集检查和风险评估模块开始。

## 成员2接手验证记录

### 已完成环境验证

- 开发环境：WSL2 + VS Code + Codex
- 仓库路径：`~/CRAFT`
- Conda 环境：`craft`
- Python 版本：`3.10.21`，符合项目要求 `>=3.10,<3.13`
- 单元测试结果：`python -m pytest -q --tb=short`
  - 结果：`14 passed in 0.12s`

### Grid2Op 数据集与仿真验证

已执行：

```bash
python scripts/download_grid2op_dataset.py list
make download-grid-data
make check-grid-real
```

### 真实 Grid2Op smoke check 结果

- `make check-grid-real`：通过
- 默认非 test 数据集：`l2rpn_2019`
- 数据目录：`data/grid2op/l2rpn_2019`

输出摘要：

```text
Grid2Op env: l2rpn_2019
  actual env: l2rpn_2019PandaPowerBackend
  backend: PandaPowerBackend_l2rpn_2019PandaPowerBackend
  lines: 20
  generators: 5
  loads: 11
  redispatchable generators: 4
  max rho during smoke test: 1.0094
  reward type: float32
  done after noop: False
```

### 当前判断

`l2rpn_2019` 已下载到项目本地数据目录，并能在非 test 模式下完成 Grid2Op reset 与 noop step。成员2可以基于该数据集继续开发真实 Grid2Op simulation callback。

## 成员2后续任务：真实 Grid2Op Simulation Callback

### Grid2Op Action 映射与 sandbox 仿真

本次目标是实现 `Grid2OpConsequenceEvaluator` 背后的真实 Grid2Op simulation callback，不重复实现已有 `craft.grid.risk`、`craft.grid.evaluator`、`craft.grid.revalidation`，不实现 SM2 真签名、CA、Dashboard 或 Agent，也不修改根目录 `README.md`。

新增/更新文件：

- `src/craft/grid/grid2op_actions.py`
- `src/craft/grid/grid2op_simulator.py`
- `src/craft/grid/__init__.py`
- `tests/test_grid2op_actions.py`
- `tests/test_grid2op_simulator.py`

实现内容：

- `action_request_to_grid2op_payload(action_request)`：按 `src/craft/grid/README.md` 的参数约定，把 CRAFT `ActionRequest.parameters` 转为 Grid2Op action payload
- `action_request_to_grid2op_action(action_space, action_request)`：调用 Grid2Op `action_space` 生成真实 action，并把 Grid2Op “ignored key” warning 转为 `Grid2OpActionError`，避免静默变成 noop
- 支持 `redispatch`、`disconnect_line`、`reconnect_line`、`change_topology`，同时允许空参数 `noop`
- 严格拒绝缺失参数、未知参数、互斥参数同时出现、重复 id、越界 id、不可 redispatch generator 和不支持 action type
- `Grid2OpSimulator`：可作为 `Grid2OpConsequenceEvaluator` 的 `simulate(action)` callback，返回 `Grid2OpStepResult(obs_before, obs_after, done, info, reward)`
- 默认 Grid2Op env 为 `l2rpn_2019`，通过 `craft.grid2op_datasets.configure_grid2op_data_dir()` 使用项目相对数据目录 `data/grid2op`
- 默认创建 Grid2Op env 时使用 `CompleteAction`，确保 redispatch action 不被默认 topology-only action class 静默忽略
- 支持传入 live env 时先 `env.copy()`，并只在 copied/sandbox env 上执行 step，避免污染 live execution environment
- 在 `info["craft_grid2op_metadata"]` 中返回 state/predicted-state metadata，并预先填充 `state_digest`、`predicted_state_digest`，便于复现 digest

测试覆盖：

- redispatch 参数映射：`{"gen_id": 2, "delta_mw": -30.0}` -> `{"redispatch": [(2, -30.0)]}`
- disconnect/reconnect line 映射到 `set_line_status`
- change_topology 的 `topology_vector` 映射到 `set_bus.substations_id`
- 缺失参数、未知参数、歧义参数、空 id 列表、不支持 action type 均抛 `Grid2OpActionError`
- Grid2Op action_space warning 包含 ignored 时拒绝，避免把请求静默变成 noop
- fake live env 通过 `copy()` 创建 sandbox，step 只发生在 sandbox 上，live env 不被污染
- fake env_factory 路径会 reset fresh sandbox
- step 异常返回 `done=True`、`obs_after=None`、`simulation_failed=True` 的失败 `Grid2OpStepResult`
- state digest 和 predicted state digest 可用返回 metadata 复现

合入主线后已运行验证：

```bash
/home/user7377/miniforge3/bin/conda run -n craft python -m pytest -q --tb=short
/home/user7377/miniforge3/bin/conda run -n craft python -m ruff check .
/home/user7377/miniforge3/bin/conda run -n craft python -m mypy src/craft
/home/user7377/miniforge3/bin/conda run -n craft make check-grid-real PYTHON=python
```

结果：

- `pytest`：`102 passed in 7.22s`
- `ruff`：`All checks passed!`
- `mypy`：`Success: no issues found in 24 source files`
- `make check-grid-real`：通过，`l2rpn_2019` reset + noop step 正常

真实 callback smoke：

```text
noop       -> L1, max rho 0.8277, redispatch_mw 0.0, converged True
redispatch -> L1, max rho 0.8260, redispatch_mw 1.0, converged True
```

备注：

- `l2rpn_2019` 中 `gen_id=0` 不可 redispatch；真实 smoke 使用可 redispatch 的 `gen_id=1`
- pytest 新增测试均使用 fake env / fake action_space，不依赖真实数据集下载

## 成员2后续任务：真实 Grid2Op 报告实验

本次目标是补充两个显式运行的真实 Grid2Op 报告实验，不重复实现已有
`craft.grid.risk`、`craft.grid.evaluator`、`craft.grid.revalidation` 或
`craft.security.protocol` 核心逻辑，不修改根目录 `README.md`，也不把真实数据集接入普通
pytest。

新增文件：

- `scripts/demo_member2_grid2op_experiments.py`

实现内容：

- 实验脚本默认使用项目相对数据目录 `data/grid2op/l2rpn_2019`
- 通过真实 Grid2Op env metadata 自动选择第一个可 redispatch generator；当前
  `l2rpn_2019` 为 `gen_id=1`
- 用 noop 从 reset episode 向前扫描状态，默认最多扫描 260 个 timestep
- 每次后果评估都通过 `Grid2OpSimulator(env=...)` 复制 live selector env，并在 copied
  sandbox env 上执行 Grid2Op step
- 实验1使用同一个 `ActionRequest(redispatch, gen_id=1, delta_mw=1.0)`，在两个真实电网
  状态下产生不同风险等级
- 实验2使用同一个 `ActionRequest(redispatch, gen_id=1, delta_mw=20.0)`，先在审批时得到
  L2 PCC，再把 execution-time metrics 接入 `consume_ticket_and_issue_receipt(...)`
  触发现有 revalidation 错误码
- 终端输出包含运行命令、数据集/env、Grid2Op version、backend、episode/timestep、动作参数、
  max rho、新增过载数、安全裕度、converged、islanding/load_shed、redispatch/topology 变化、
  RiskLevel、required roles、action digest、PCC digest、policy digest、state/predicted
  digest 和 revalidation code/decision

实验状态选择结果：

- 实验1：
  - episode `0001` timestep `0`：`delta_mw=1.0`，`max_rho=0.8260`，`RiskLevel=L1`
  - episode `0001` timestep `2`：`delta_mw=1.0`，`max_rho=0.8665`，`RiskLevel=L2`
- 实验2：
  - approval-time episode `0001` timestep `0`：`delta_mw=20.0`，`max_rho=0.8021`，
    `RiskLevel=L2`
  - execution-time episode `0001` timestep `48`：`max_rho=0.9824`，`RiskLevel=L3`，
    protocol code `revalidation_required`，decision `require_reauthorization`
  - execution-time episode `0001` timestep `231`：`converged=false`，`RiskLevel=REJECT`，
    protocol code `revalidation_rejected`，decision `reject`

本次没有修改 risk 阈值、ActionRequest 到 Grid2Op action 的映射、默认数据集路径或普通测试策略。

运行方式：

```bash
conda run --no-capture-output -n craft python scripts/demo_member2_grid2op_experiments.py
conda run --no-capture-output -n craft python scripts/demo_member2_grid2op_experiments.py --output artifacts/grid/member2_grid2op_report_experiments.json
```

默认会同时生成 JSON 报告产物：

```text
artifacts/grid/member2_grid2op_report_experiments.json
```

`artifacts/` 已被 Git 忽略。报告撰写时可以截图终端输出，也可以从 JSON 中复制实验表格、metrics、digest 和 revalidation code。

已运行验证：

```bash
conda run -n craft python -m pytest -q --tb=short
conda run -n craft python -m ruff check .
conda run -n craft python -m mypy src/craft
conda run -n craft make check-grid-real PYTHON=python
conda run --no-capture-output -n craft python scripts/demo_member2_grid2op_experiments.py
```

结果：

- `pytest`：`103 passed in 8.13s`
- `ruff`：`All checks passed!`
- `mypy`：`Success: no issues found in 24 source files`
- `make check-grid-real`：通过，`max rho during smoke test: 1.0094`，`done after noop: False`
- `demo_member2_grid2op_experiments.py`：通过，观察到 `revalidation_required` 和
  `revalidation_rejected`，并生成 `artifacts/grid/member2_grid2op_report_experiments.json`
