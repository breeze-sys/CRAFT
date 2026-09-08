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
- 当前本地磁盘占用：约 `276M`

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

`l2rpn_2019` 已下载到项目本地数据目录，并能在非 test 模式下完成 Grid2Op reset 与 noop step。成员2可以基于该数据集继续开发 Consequence Evaluator、Risk Engine 和执行前 Revalidation。

## 成员2第一阶段代码实现记录

### 最小 Risk Engine

本次只实现 Risk Engine，不实现 Grid2Op evaluator 和 revalidation。

新增文件：

- `src/craft/risk_engine.py`
- `tests/test_risk_engine.py`

实现内容：

- 输入：已有 `ConsequenceMetrics`
- 输出：已有 `RiskLevel`
- 默认入口：`evaluate_risk(metrics)`
- 可复用对象：`RiskEngine`、`RiskThresholds`、`DEFAULT_RISK_ENGINE`

默认风险规则：

- `REJECT`：不收敛、孤岛、负荷切除、非有限数值、严重线路越限 `max_line_loading_ratio >= 1.20`、新增过载线路数 `>= 3`
- `L3`：线路负载率 `>= 0.95`、轻微越限如 `max_line_loading_ratio = 1.01`、新增过载线路数为 1 到 2、redispatch 幅度 `>= 50 MW`、断线、拓扑变化子站数 `>= 3`
- `L2`：线路负载率 `>= 0.85`、redispatch 幅度 `>= 20 MW`、存在少量拓扑变化
- `L1`：未触发以上条件的低风险动作

测试覆盖：

- `max_line_loading_ratio` 阈值边界：`0.85`、`0.95`、`1.20`
- 轻微越限：`1.01` 判为 `L3`，不直接 `REJECT`
- 新增过载线路数边界：`0/1/2/3`
- redispatch、拓扑变化、断线的风险升级边界
- 不收敛、孤岛、负荷切除、非有限数值的拒绝路径

## 成员2第二阶段代码实现记录

### Grid2Op Consequence Evaluator 指标抽取

本次只实现 Grid2Op consequence metrics extraction，不实现 revalidation，不修改根目录 `README.md`，也不修改已有协议模型语义。

新增文件：

- `src/craft/grid2op_evaluator.py`
- `tests/test_grid2op_evaluator.py`

实现内容：

- `extract_consequence_metrics(obs_before, obs_after, done, info, action_request)`：把 Grid2Op step 前后 observation、`done`、`info` 和已有 `ActionRequest` 转成已有 `ConsequenceMetrics`
- `evaluate_consequence_risk(metrics)`：调用第一阶段 `risk_engine.evaluate_risk(metrics)`，返回已有 `RiskLevel`
- 支持 `noop` 和 `redispatch` 的指标抽取；`redispatch_mw` 从 `ActionRequest.parameters` 中的 `delta_mw`、`redispatch_mw` 等字段提取绝对 MW 幅度

当前抽取的指标：

- `max_line_loading_ratio`：来自 `obs_after.rho` 的最大有限值
- `new_overload_count`：统计 before 未越限但 after 越限的线路数
- `min_security_margin`：`1.0 - max_line_loading_ratio`
- `converged`：`obs_after` 存在、`done=False`、`rho` 有限且 `info` 未报告异常时为 true
- `islanding`：从 `info` 中的 islanding 相关字段提取
- `load_shed_mw`：优先从 `info` 中的 load shed 相关字段提取
- `redispatch_mw`：从 redispatch 类型 `ActionRequest` 参数提取
- `disconnected_line_count`：优先比较 `line_status` before/after，缺少 observation 时可从 disconnect action 参数估计
- `topology_changed_substations`：优先结合 `topo_vect` 和 `sub_info` 比较变化子站数，缺少 observation 时可从 topology action 参数估计

测试覆盖：

- fake observation 下的 noop 指标抽取
- redispatch 的绝对 MW 幅度提取，并通过 `evaluate_consequence_risk` 得到 `L2`
- `max_line_loading_ratio = 1.0094` 的轻微越限路径判为 `L3`，不直接 `REJECT`
- `done=True` 和 `info["exception"]` 导致 `converged=False` 并判为 `REJECT`
- islanding、load shed、断线、拓扑变化子站数的指标抽取

已运行验证：

```bash
/home/user7377/miniforge3/bin/conda run -n craft python -m pytest -q --tb=short
/home/user7377/miniforge3/bin/conda run -n craft python -m ruff check src/craft/grid2op_evaluator.py tests/test_grid2op_evaluator.py src/craft/risk_engine.py tests/test_risk_engine.py
/home/user7377/miniforge3/bin/conda run -n craft python -m mypy src/craft/grid2op_evaluator.py src/craft/risk_engine.py
```

结果：

- `pytest`：`42 passed in 0.14s`
- `ruff`：`All checks passed!`
- `mypy`：`Success: no issues found in 2 source files`

补充检查：

- `python -m ruff check .`：通过
- `python -m mypy src/craft`：当前仍有既有模块类型检查问题，涉及 `serialization.py`、`grid2op_datasets.py`、`grid2op_health.py`；本次新增的 `grid2op_evaluator.py` 和第一阶段 `risk_engine.py` 类型检查已单独通过

## 成员2第三阶段代码实现记录

### Execution-Time Revalidation

本次只实现审批后、执行前的风险重验证决策逻辑，不实现 SM2 真签名、CA、Dashboard、Agent，也不引入真实 Grid2Op 数据集依赖；未修改根目录 `README.md`，未修改已有协议模型语义。

新增文件：

- `src/craft/revalidation.py`
- `tests/test_revalidation.py`

实现内容：

- `RevalidationResult`：返回 `decision`、`approval_risk_level`、`execution_risk_level`、`reason`
- `RISK_LEVEL_ORDER` / `risk_level_rank(risk_level)`：定义风险等级顺序 `L1 < L2 < L3 < REJECT`
- `revalidate_execution(approval_pcc, execution_metrics)`：输入审批时 `PhysicalConsequenceCertificate` 和执行前 `ConsequenceMetrics`，通过 `risk_engine.evaluate_risk(metrics)` 重新计算 execution-time risk
- `decide_revalidation(approval_risk_level, execution_risk_level)`：执行最终决策

默认决策规则：

- execution risk 为 `REJECT`：返回 `ExecutionDecision.REJECT`
- execution risk 高于 approval-time risk：返回 `ExecutionDecision.REQUIRE_REAUTHORIZATION`
- execution risk 小于或等于 approval-time risk：返回 `ExecutionDecision.ALLOW`

测试覆盖：

- `L1 -> L1`：`allow`
- `L2 -> L1`：`allow`
- `L1 -> L2`：`require_reauthorization`
- `L2 -> L3`：`require_reauthorization`
- `L3 -> REJECT`：`reject`
- `REJECT -> REJECT`：`reject`

已运行验证：

```bash
/home/user7377/miniforge3/bin/conda run -n craft python -m pytest -q --tb=short
/home/user7377/miniforge3/bin/conda run -n craft python -m ruff check src/craft/revalidation.py tests/test_revalidation.py src/craft/grid2op_evaluator.py tests/test_grid2op_evaluator.py src/craft/risk_engine.py tests/test_risk_engine.py
/home/user7377/miniforge3/bin/conda run -n craft python -m mypy src/craft/revalidation.py src/craft/grid2op_evaluator.py src/craft/risk_engine.py
```

结果：

- `pytest`：`48 passed in 0.14s`
- `ruff`：`All checks passed!`
- `mypy`：`Success: no issues found in 3 source files`
