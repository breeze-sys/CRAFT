# CRAFT

**CRAFT: Consequence-aware Risk-Adaptive Framework for Trusted Execution of AI-Driven Power Grid Agents**

中文工作题目：**面向 AI 电网智能体可信执行的后果感知风险自适应框架**

> 说明：这里的 `Trusted Execution` 指“可信执行流程与可验证责任链”，不是硬件意义上的 TEE。第一版不把 TEE 作为实现目标。

## 1. Project Positioning

CRAFT 面向 AI Agent 参与电网调度和控制的安全问题。随着 LLM Agent 能够调用电力分析工具、生成调度方案并提交控制动作，传统“身份认证 + 静态接口权限”已经不足以表达电力控制的真实风险：同一个动作在不同电网运行状态下，可能从低风险变成接近过载、孤岛或负荷切除的高风险操作。

CRAFT 的核心目标是构建一套可运行的应用密码系统：

```text
Agent Proposal
  -> Physical Consequence Evaluation
  -> Risk-Adaptive Authorization
  -> Cryptographic Binding
  -> Pre-Execution Revalidation
  -> Trusted Execution
  -> Signed Receipt
```

系统不依赖 LLM 自律，不让 Agent 直接获得物理执行接口，而是把所有状态改变操作交给独立的 CRAFT Gateway 审核、授权、再验证和执行。

## 2. Core Problem

传统身份认证主要回答：

```text
Who is calling the interface?
```

传统访问控制主要回答：

```text
Is this caller allowed to call this interface?
```

但电力系统还必须回答：

```text
What physical consequence will this exact action cause under the current grid state?
```

例如同样执行：

```text
Redispatch(generator=G2, delta=+30 MW)
```

在普通状态下可能只需 Operator 单签；如果相邻线路已经接近热稳定极限，则可能需要 Operator、Dispatcher 和 Safety Officer 联合授权，甚至被 Safety Gate 直接拒绝。

CRAFT 的核心判断链为：

```text
GridState + Action
  -> PredictedPhysicalConsequence
  -> RiskLevel
  -> RequiredRoles
  -> CryptographicApproval
```

## 3. Main Contributions

**贡献一：物理后果驱动的风险自适应授权**

CRAFT 不采用固定的 `ActionType -> RiskTier` 规则，而是通过 `R = f(state, action)` 计算当前动作的物理风险，再映射到认证强度：

```text
L1 -> Operator
L2 -> Operator + Dispatcher
L3 -> Operator + Dispatcher + Safety Officer
Reject -> Unsafe action, no authorization path
```

可使用的物理指标包括最大线路负载率、新增过载线路数量、安全裕度变化、潮流是否收敛、拓扑变化范围、是否发生孤岛、是否触发负荷切除、redispatch 幅度等。

**贡献二：物理后果证书 PCC 与审批绑定**

CRAFT 为每个候选动作生成 Physical Consequence Certificate，简称 PCC。PCC 由独立 Consequence Evaluator 产生并签名，它不是数学意义上的“物理安全证明”，而是“在指定模型、状态和策略下得到的可验证物理后果声明”。

建议 PCC 字段：

```json
{
  "pcc_id": "uuid",
  "state_digest": "SM3(canonical_grid_state)",
  "action_digest": "SM3(canonical_action)",
  "predicted_state_digest": "SM3(canonical_predicted_state)",
  "metrics": {
    "max_line_loading": 0.91,
    "new_overload_count": 0,
    "min_security_margin": 0.09,
    "converged": true,
    "islanding": false,
    "load_shed_mw": 0
  },
  "risk_level": "L2",
  "policy_digest": "SM3(canonical_policy)",
  "simulator": {
    "name": "Grid2Op",
    "env": "l2rpn_case14_sandbox",
    "version": "..."
  },
  "issued_at": "ISO-8601 timestamp",
  "expires_at": "ISO-8601 timestamp",
  "evaluator_signature": "SM2.Sign(evaluator_sk, SM3(canonical_pcc))"
}
```

审批者签名绑定的是动作、PCC、策略、Nonce 和有效期：

```text
Approval_i =
  SM2.Sign(role_i_sk,
    SM3(Action || PCC || PolicyDigest || Nonce || Expiry)
  )
```

因此，攻击者修改动作参数、PCC、风险等级、策略版本、审批有效期或审批者身份，都会导致验证失败。

**贡献三：状态漂移感知的动态再授权**

人工审批和真实执行之间可能存在十几秒甚至几十秒延迟。电力系统状态持续变化，如果简单要求审批状态哈希和执行状态哈希完全一致，微小负荷波动也会让授权频繁失效；如果完全不检查状态变化，又可能拿低风险授权执行高风险动作。

CRAFT 的策略是执行前重新仿真：

```text
R_a = risk at approval time
R_e = risk at execution time

if Safe(PCC_e) == false:
  reject
elif R_e <= R_a:
  allow existing approval
else:
  require re-authorization
```

这样比单纯比较 `StateSnapshotHash` 更适合连续变化的电力 CPS 场景。

## 4. Non-Claims

以下内容只能作为工程支撑或相关工作借鉴，不应单独写成“首创”：

1. Agent 运行时安全网关。
2. 数字孪生执行前验证。
3. 风险分级审批。
4. 多角色签名审批。
5. Action Hash、State Hash、Policy Digest、Nonce、Expiry、Replay Cache。
6. 执行回执和哈希链审计。
7. “用密码防 Prompt Injection”这一宽泛表述。

更稳妥的创新表述是：

```text
CRAFT 将电网动作的实时物理后果作为密码授权策略输入，
并在审批后状态漂移导致风险升级时触发动态再认证。
```

## 5. Security Principle

CRAFT 必须保持 Safety Gate 和 Authority Gate 分离。

**Safety Gate** 判断：

```text
Can this action be physically accepted?
```

如果仿真发现严重过载、孤岛、潮流不收敛、违反硬约束或不允许的负荷切除，则直接拒绝。即使审批角色全部签名，也不能执行。

**Authority Gate** 判断：

```text
Who is authorized to approve this physically acceptable action?
```

只有动作通过物理安全检查后，系统才根据风险等级验证角色策略和签名集合。

最终执行条件：

```text
Execute(action) iff Safe(state, action) and AuthorizationSatisfied(action)
```

## 6. System Architecture

推荐第一版系统结构：

```text
                   User / Operator
                         |
                         v
                +----------------+
                |   LLM Agent    |
                +-------+--------+
                        |
                        | Proposed Action
                        v
             +------------------------+
             |     CRAFT Gateway      |
             +------------------------+
             | Action Normalizer      |
             | Consequence Evaluator  |
             | Risk Engine            |
             | Policy Engine          |
             | SM2 Approval Verifier  |
             | Revalidation Engine    |
             | Execution Ticket Issuer|
             +-----------+------------+
                         |
              +----------+----------+
              |                     |
              v                     v
       Approval Dashboard      Grid2Op Simulator
       Operator                Digital Twin
       Dispatcher
       Safety Officer
              |
              | SM2 Signatures
              v
        Execution Gateway
              |
              v
           Grid2Op
              |
              v
   Signed Execution Receipt
```

关键不变量：

```text
Agent never receives direct access to the execution interface.
```

## 7. Protocol Flow

第一版建议实现 8 个阶段：

1. Agent 根据用户指令和观测信息生成结构化候选动作。
2. CRAFT Gateway 对动作做 canonicalization 和 schema validation。
3. Consequence Evaluator 调用 Grid2Op，在当前状态下预演动作后果。
4. Risk Engine 提取指标并计算风险等级。
5. Evaluator 生成并签名 PCC。
6. Policy Engine 根据 `risk_level` 计算所需角色集合。
7. 审批角色对 `Action || PCC || PolicyDigest || Nonce || Expiry` 进行 SM2 签名。
8. 执行前重新仿真，若风险未升级则签发 Execution Ticket，执行后产生 Receipt。

建议核心对象：

```text
ActionRequest
PCC
Approval
ApprovalSet
ExecutionTicket
ExecutionReceipt
AuditEvent
```

## 8. Threat Model

第一版威胁模型应覆盖：

1. Prompt Injection 操纵 Agent。
2. Agent 产生恶意 Tool Call。
3. 攻击者篡改候选动作参数。
4. 攻击者重放旧授权。
5. 攻击者拿低风险授权执行高风险动作。
6. 审批后动作被修改。
7. 审批后电网状态变化，但继续尝试使用旧授权。
8. 非授权角色冒充 Operator、Dispatcher 或 Safety Officer。
9. 单个角色私钥泄露，但攻击者无法满足完整角色策略。
10. 审计记录被篡改。

对应安全性质：

```text
Action Integrity:
  action' != action -> Approval(action) cannot execute action'

Consequence Binding:
  PCC' != PCC -> Approval(PCC) cannot approve PCC'

Risk Non-Downgrade:
  R_execution > R_approval -> low-risk approval cannot execute high-risk action

Role Conformance:
  RoleSet does not satisfy Policy(R) -> reject

Replay Resistance:
  Used(Nonce) == true -> reject
```

## 9. MVP Scope

一个月版本必须控制范围，目标是可演示、可复现、可解释。

必须完成：

1. Grid2Op 小规模环境，优先 `l2rpn_case14_sandbox` 或 `educ_case14_redisp`。
2. 基础 Agent，可以是真 LLM，也必须有 scripted fallback。
3. 5 到 7 个电力工具：`query_grid_state`、`get_overloaded_lines`、`redispatch`、`disconnect_line`、`reconnect_line`、`change_topology`、可选 `shed_load`。
4. Consequence Evaluator、Risk Engine、Policy Engine。
5. PCC、Approval、Execution Ticket、Execution Receipt。
6. SM2/SM3 签名与摘要，简单 CA 和角色证书。
7. 三类角色：Operator、Dispatcher、Safety Officer。
8. Approval Dashboard 和 Audit View。
9. 执行前 State Revalidation。
10. 五类核心 Demo 和基本测试。

可以作为后续增强：

1. SM4 加密敏感遥测或日志。
2. MCP 标准适配。
3. PowerMCP 或 PowerAgentBench 集成。
4. IEEE 39-bus 或更复杂 case。
5. Docker 和一键部署。
6. 更完整的审计可视化。

第一版不做：

1. 真正门限签名。
2. TEE。
3. ZKP。
4. 区块链。
5. 后量子签名。
6. 真实 SCADA/PLC。
7. 工业级 PKI。
8. 自己训练电力大模型。

## 10. Environment Setup

推荐使用 Python 3.10。默认 Python 3.13 对 Grid2Op、pandapower、lightsim2grid 等科学计算和电力仿真依赖可能存在兼容风险，因此项目配置约束为：

```text
Python >=3.10,<3.13
```

如果使用 conda：

```bash
cd /home/breeze/my-project/CRAFT
conda env create -f environment.yml
conda activate craft
python scripts/check_environment.py
```

如果 `repo.anaconda.com` 连接失败，可以改用镜像版：

```bash
cd /home/breeze/my-project/CRAFT
conda env create -f environment-cn.yml
conda activate craft
python scripts/check_environment.py
```

如果使用本地虚拟环境：

```bash
cd /home/breeze/my-project/CRAFT
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/check_environment.py
```

常用开发命令：

```bash
make setup
make setup-local
make check
make test
make lint
make format
```

`make setup-local` 只安装 CRAFT 项目自身，不安装第三方依赖，适合包源暂时不可达时先跑本地脚本。

当前仓库已经包含：

1. `pyproject.toml`：Python 包元数据、运行依赖、开发依赖和工具配置。
2. `environment.yml`：conda 环境定义。
3. `environment-cn.yml`：使用清华镜像的 conda 环境定义。
4. `requirements.txt` 和 `requirements-dev.txt`：pip 安装入口。
5. `.env.example`：本地环境变量模板。
6. `src/craft`：后续核心代码包。
7. `scripts/check_environment.py`：环境健康检查脚本。
8. `tests`：基础测试目录。

注意：`.env`、虚拟环境、缓存、构建产物和密钥文件已在 `.gitignore` 中排除。

更详细的本机安装说明和故障排查见 `docs/setup.md`。也可以直接运行：

```bash
bash scripts/bootstrap_env.sh
```

## 11. Demo Plan

**Demo 1：正常低风险操作**

低幅度 redispatch 被评估为 L1，只需要 Operator 单签，执行成功并生成回执。

**Demo 2：同一动作不同状态触发不同认证**

同样的 `Redispatch(+30 MW)` 在 State A 下为 L1，在 State B 下为 L3，展示物理后果改变密码认证强度。这是最核心演示。

**Demo 3：Prompt Injection 隔离**

用户或外部输入诱导 Agent 生成危险动作，例如 `Disconnect Line 3`。Agent 即使提出该动作，也不能绕过 CRAFT Gateway，必须经过仿真、风险分级和多角色授权。

**Demo 4：审批后参数篡改**

审批时为 `Redispatch +20 MW`，攻击者改成 `Redispatch +80 MW`。Action Digest 不匹配，签名验证失败，执行被拒绝。

**Demo 5：状态漂移触发再授权**

审批时风险为 L1；等待期间修改环境状态，执行前重新仿真得到 L3。系统提示风险升级，原授权失效，需要 Operator、Dispatcher 和 Safety Officer 重新审批。

## 12. Evaluation Metrics

安全实验：

1. Action tampering detection rate。
2. Replay detection rate。
3. Unauthorized-role rejection rate。
4. Risk downgrade rejection rate。
5. Stale authorization detection rate。
6. Unsafe action rejection rate。

性能实验：

1. `T_simulate`：Grid2Op 仿真耗时。
2. `T_pcc`：PCC 生成与签名耗时。
3. `T_sm2_verify`：审批签名验证耗时。
4. `T_revalidate`：执行前重验证耗时。
5. `T_gateway`：网关端到端处理耗时。

系统实验：

1. 低风险单签动作。
2. L2 双角色动作。
3. L3 三角色动作。
4. Risk escalation。
5. 多个电网运行点下的同动作风险变化。

注意：人工审批等待时间不应计入密码协议本身性能。

## 13. Team Split

三人开发时可以按边界并行：

**A：密码协议与安全模块**

负责 PCC 格式、SM2/SM3、CA/Role Credential、Approval、Execution Ticket、Receipt、威胁模型和协议安全性质。

**B：电力环境与 Gateway**

负责 Grid2Op、Action/Observation、Consequence Evaluator、Risk Engine、Risk Policy、State Revalidation。

**C：Agent 与系统展示**

负责 LLM Agent 或 scripted Agent、Tool Adapter、Web Dashboard、Approval UI、Audit UI、攻击 Demo 和系统集成。

## 14. Reporting Angle

作品报告建议围绕以下主线写：

```text
背景问题：
AI Agent 进入电力控制后，静态接口权限无法表达实时物理风险。

核心思想：
把电网物理后果作为密码授权策略输入。

技术路线：
数字孪生预演 -> PCC -> 风险自适应多角色签名 -> 执行前再验证 -> 执行票据 -> 签名回执。

创新边界：
不声称发明基础密码算法或普通 Agent 网关，主打电力物理后果与密码授权强度的动态绑定。

实验验证：
用 Grid2Op 小规模电网和攻击 Demo 展示动作篡改、重放、越权、风险升级和不安全动作均被拦截。
```

可复用的核心表述：

> 现有 AI Agent 授权机制通常依据操作类别、权限范围或静态风险等级决定是否允许执行；然而在电力系统中，同一控制动作的实际风险高度依赖实时运行状态，导致静态授权无法准确反映物理控制后果。CRAFT 面向 AI 电网智能体可信执行，构建物理后果驱动的密码授权机制：首先利用电网数字孪生对 Agent 候选动作进行执行前仿真，生成由可信评估器签名的物理后果证书 PCC，并依据预计线路负载、拓扑变化、安全裕度等指标动态确定多角色认证强度；随后利用 SM2/SM3 将控制动作、物理后果、授权策略和审批者身份进行密码绑定。针对电网状态持续变化带来的审批到执行状态漂移问题，系统在真实执行前重新评估当前物理后果，当风险等级升级时使原授权失效并触发动态再认证，从而形成“智能体决策、物理验证、密码授权、动态再验证、可信执行、密码回执”的完整安全闭环。

## 15. References

1. ChatGPT planning summary: https://chatgpt.com/s/t_6a95692e05ac81918e8c02daebcb5fa9
2. TwinGridShield: https://arxiv.org/abs/2608.15391
3. OT Command Authority Internet-Draft: https://datatracker.ietf.org/doc/draft-morrison-ot-command-authority/
4. AgentROA Internet-Draft: https://datatracker.ietf.org/doc/draft-nivalto-agentroa-route-authorization/01/
5. Grid2Op documentation: https://grid2op.readthedocs.io/
6. Grid2Op available environments: https://grid2op.readthedocs.io/en/latest/available_envs.html
7. PowerMCP: https://github.com/Power-Agent/PowerMCP
8. PowerAgentBench: https://github.com/Power-Agent/PowerAgentBench
