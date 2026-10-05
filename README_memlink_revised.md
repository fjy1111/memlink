# memlink

> 面向多智能体协作的轻量运行时：让控制消息更规范，让数值状态少搬运，让已经验证的结果可以安全复用。

**memlink** 是一个面向 openEuler / Linux 环境的多 Agent 运行时原型。项目关注的不是“如何再做一个 Agent 框架”，而是多 Agent 在真实运行过程中经常出现的三个系统问题：

1. Agent 之间的控制消息缺少统一数据契约，大对象容易被反复展开；
2. NumPy 数组等非文本状态在 Agent 间传递时容易退化为文本或 JSON；
3. 历史结果即使已经验证正确，也往往无法安全地直接复用，造成重复模型调用和重复执行。

memlink 因此把系统拆成三条独立但可以组合的路径：

```text
Control Plane     AgentEnvelope + ArtifactRef
State Plane       StateRef + SharedMemory
Reuse Plane       MemoryService + Evaluator-Validated Fast Path
```

参赛作品名称统一为 **memlink**。为保持已有工程兼容性，Python 包名、CLI 与环境变量前缀仍沿用早期工程名 `agentipc` / `AGENTIPC_*`。

---

## 1. 项目定位

memlink 的目标不是替代 LangGraph、AutoGen 等编排框架，而是在多 Agent 协作链路中验证一组更偏“系统层”的机制：

- 用结构化消息模型约束 Agent 间交互；
- 将大对象和数值状态从控制消息中分离；
- 在 Linux 共享内存上通过引用传递 NumPy 状态；
- 将“检索到记忆”和“允许跳过执行”严格区分；
- 对历史 RESULT 引入 evaluator 验证后再进入 Fast Path；
- 对通信、状态、记忆、模型调用和时延统一记录证据。

系统默认提供 Planner、Retriever、Executor、Summarizer 四个角色，用于形成稳定、可追踪的实验链路。

```text
User Task
   │
   ▼
Planner
   │
   ▼
Retriever
   │
   ▼
Executor
   │
   ▼
Summarizer
   │
   ▼
Final Result
```

---

## 2. 三个核心机制

### 2.1 AgentEnvelope：控制链路的数据契约

Agent 间消息统一使用 `AgentEnvelope` 表达。Envelope 中记录：

- `message_id / trace_id / task_id / step_id`
- `sender / receiver`
- `message_type / action / capability`
- `args / result`
- `state_refs / artifact_refs / memory_refs`
- `status / metrics`

结构化协议的首要作用是**统一协作语义、约束字段并增强可观测性**，而不是简单宣称“结构化消息一定比文本更小”。

对于不适合直接放入消息的大对象，memlink 使用 `ArtifactRef`：

```text
Large Object
    │
    ▼
ArtifactStore
    │
    └── ArtifactRef ──► AgentEnvelope
```

控制链路只携带引用和必要元数据，实际对象独立保存。

核心代码：

```text
src/agentipc/protocol/
src/agentipc/artifacts/
```

---

### 2.2 StateRef + SharedMemory：跨进程非文本状态交换

对于 NumPy 数组、计划向量等数值状态，memlink 不要求将数组内容重新展开到 Agent 消息中。

```text
NumPy ndarray
    │
    ▼
StateHub.put_array(...)
    │
    ├── inproc
    └── Linux SharedMemory
             │
             ▼
          StateRef
             │
             ▼
       AgentEnvelope
             │
             ▼
StateHub.resolve_array(...)
```

`StateRef` 保存状态定位和校验所需的元数据，例如：

```text
uri
kind
shape
dtype
nbytes
checksum
transport
summary
```

接收端根据引用恢复状态，并校验 shape、dtype、nbytes 和 checksum。

当前实现**不宣称完全 zero-copy**：SharedMemory 可以避免在控制链路中传输完整数值内容，但 `resolve_array()` 返回独立 NumPy 数组时仍会产生一次数据复制。

核心代码：

```text
src/agentipc/state/hub.py
src/agentipc/state/shared_memory.py
src/agentipc/protocol/refs.py
```

---

### 2.3 Evaluator-Validated Memory Fast Path：只复用被验证过的结果

memlink 将普通“记忆检索”和“直接复用结果”分成两件事。

普通检索可以综合：

```text
semantic similarity
+ keyword overlap
+ tag overlap
```

但检索命中本身**不会**让系统跳过正常 Agent 链路。

只有满足严格条件的历史结果才允许进入 Fast Path：

```text
Exact Task Match
        +
MemoryType.RESULT
        +
External Evaluator Passed
        +
可用的结果内容
        │
        ▼
Validated Memory Fast Path
```

如果不满足条件，系统继续执行正常 Planner → Retriever → Executor → Summarizer 链路。

这样做的重点不是“尽可能多地命中记忆”，而是减少相似任务误复用带来的错误传播。

核心代码：

```text
src/agentipc/memory/service.py
src/agentipc/memory/sqlite_store.py
src/agentipc/memory/vector_index.py
```

---

## 3. A/B/C/D 实验模式

项目保留四种运行模式用于逐层开启机制：

| 模式 | 运行配置 | 主要用途 |
| --- | --- | --- |
| A | Text Baseline | 纯文本通信基线 |
| B | Structured | 启用结构化 AgentEnvelope |
| C | Structured + State | 在 B 基础上加入 StateRef |
| D | Full | 在 C 基础上加入共享记忆与结果复用 |

A/B/C/D 用于观察不同基础设施机制是否真正进入执行链路，并记录：

- message count
- text chars / protocol bytes
- state transfer count / state bytes
- memory retrieved / used / effective / harmful
- LLM calls / provider tokens
- tool calls
- latency
- task success / evaluator result

离线 `mock` benchmark 主要用于稳定、确定性地复现执行链路；真实模型正式实验与冻结结果应以 `tests/evidence/`、正式报告和项目说明书中的记录为准。

---

## 4. 正式实验验证

项目将关键能力拆成独立实验，避免仅凭一个端到端数字解释所有收益。

### E6：Validated Memory Fast Path

E6 验证“只有经过 evaluator 验证的精确历史 RESULT 才能跳过重复执行”。

已保存的正式结果中：

- Knowledge：Evaluation Pass 100%，Fast Hits 15，Harmful 0%，LLM Calls 下降 50%；
- CodeAct：Evaluation Pass 100%，Fast Hits 15，Harmful 0%，LLM Calls 下降 50%；
- Fast-path Safety PASS；
- Infrastructure PASS。

E6 的重点是**安全复用**，而不是把普通语义相似度命中当作可直接复用结果。

### E7：Linux SharedMemory + StateRef

E7 使用独立进程验证真实 SharedMemory 状态交换。

代表性正式结果：

| 状态规模 | Wire Bytes Saving | Wire Tokens Saving | Latency Reduction | Correctness |
| --- | ---: | ---: | ---: | ---: |
| 4 KiB | 95.07% | 97.06% | 5.33% | 100% |
| 256 KiB | 99.95% | 99.96% | 96.17% | 100% |

该实验同时体现一个边界：SharedMemory 有固定管理开销，因此小状态的时延收益有限；状态规模增大后收益才更加明显。

### E8：完整系统

E8 在完整链路上验证协议、状态和安全复用机制组合后的效果。

正式结果包含 **120 / 120** 条成功记录，Evaluation Pass 为 **100%**。在该实验设置的 **50% 新任务 + 50% evaluator-validated exact-repeat** 工作负载下：

- Provider Tokens：下降 46.76%
- LLM Calls：下降 50.00%
- Messages：下降 50.00%
- Wire Tokens：下降 49.17%
- Wire Bytes：下降 48.36%
- Tool Calls：下降 50.00%
- Mean Latency：下降 47.22%

这些整体收益与实验中的 exact-repeat 比例密切相关，**不应泛化为所有未知新任务都固定获得约 50% 的性能提升**。

---

## 5. Dashboard 与运行证据

memlink 提供本地 Dashboard，用于查看：

- Run 元信息；
- A/B/C/D 指标；
- Agent Timeline；
- PLAN / RETRIEVE / EXECUTE / SUMMARIZE 执行轨迹；
- Non-text State Exchange；
- Shared Memory 使用情况；
- openEuler / Python / Provider 环境信息；
- 已保存的 E6 / E7 / E8 正式实验只读证据。

Dashboard 的目标不是生成新的实验结论，而是让系统运行路径和正式结果更容易被检查。

启动：

```bash
agentipc dashboard \
  --host 0.0.0.0 \
  --port 8000 \
  --results-dir results
```

浏览器访问：

```text
http://127.0.0.1:8000/dashboard/
```

---

## 6. 运行环境

推荐环境：

- openEuler 24.03-LTS-SP3
- Python >= 3.10
- Bash
- 单机 Linux

基础依赖：

```text
pydantic >= 2.0, < 3.0
numpy >= 1.24
psutil >= 5.9
PyYAML >= 6.0
```

Dashboard 可选依赖：

```text
fastapi
uvicorn
httpx
```

真实模型路径可选使用：

```text
openai-compatible provider
sentence-transformers
tiktoken
```

Windows 可用于开发与部分调试；正式 SharedMemory 与 openEuler 验证以 Linux 环境为准。

---

## 7. 获取与安装

```bash
git clone https://github.com/fjy1111/memlink.git
cd memlink
git checkout master
```

推荐使用项目脚本安装：

```bash
bash scripts/install.sh
source .venv/bin/activate
```

确认 CLI：

```bash
agentipc version
```

也可以手动安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,dashboard]"
```

---

## 8. 快速运行

### 8.1 环境检查

```bash
agentipc doctor
```

正常环境下应看到：

```text
Overall: PASS
```

### 8.2 离线 Demo

```bash
agentipc demo --provider mock
```

该命令不需要外部模型 API，适合快速确认 A/B/D 基础链路能够工作。

### 8.3 Smoke Benchmark

```bash
agentipc benchmark \
  --suite smoke \
  --repeat 3 \
  --seed 42 \
  --provider mock \
  --results-root results
```

结果目录包含：

```text
environment.json
raw.jsonl
report.md
summary.json
```

### 8.4 连续任务

Knowledge：

```bash
agentipc run-scenario knowledge \
  --provider mock \
  --seed 42 \
  --results-root results \
  --scenario-root scenarios
```

CodeAct：

```bash
agentipc run-scenario codeact \
  --provider mock \
  --seed 42 \
  --results-root results \
  --scenario-root scenarios
```

---

## 9. 测试与 openEuler 验证

完整测试：

```bash
bash scripts/run_tests.sh
```

或：

```bash
python -m pytest -q
```

按模块测试：

```bash
bash scripts/run_tests.sh tests/protocol
bash scripts/run_tests.sh tests/state
bash scripts/run_tests.sh tests/memory
```

openEuler 一键验证：

```bash
bash scripts/verify_openeuler.sh
```

验证流程包括：

```text
Environment Check
      │
      ▼
agentipc doctor
      │
      ▼
pytest
      │
      ▼
offline demo
      │
      ▼
benchmark
      │
      ▼
output validation
```

---

## 10. 项目结构

```text
memlink/
├── README.md
├── pyproject.toml
├── .env.example
├── configs/
├── src/
│   └── agentipc/
│       ├── agents/
│       ├── artifacts/
│       ├── dashboard/
│       ├── evaluation/
│       ├── experiments/
│       ├── memory/
│       ├── protocol/
│       ├── providers/
│       ├── runtime/
│       ├── sandbox/
│       └── state/
├── scenarios/
├── scripts/
├── tests/
│   └── evidence/
├── artifacts/
├── docs/
├── demo/
└── presentation/
```

其中：

- `src/agentipc/`：运行时代码；
- `tests/`：单元、集成、回归及实验验证；
- `tests/evidence/`：正式实验和冻结证据；
- `docs/`：比赛文档；
- `demo/`：可验证演示材料；
- `presentation/`：决赛 PPT 与演示视频。

---

## 11. 配置说明

仓库提供 `.env.example`。真实 `.env` 和 API Key 不应提交到 Git。

常用离线变量：

```bash
export AGENTIPC_PYTHON=python3
export AGENTIPC_VENV_DIR=.venv
export AGENTIPC_BENCHMARK_PROVIDER=mock
export AGENTIPC_BENCHMARK_SEED=42
export AGENTIPC_BENCHMARK_REPEAT=3
export AGENTIPC_RESULTS_ROOT=results
```

OpenAI-compatible provider 可参考：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
AGENTIPC_LLM_MODEL
AGENTIPC_EMBEDDING_MODEL
AGENTIPC_EMBEDDING_DIM
```

---

## 12. 复现原则

项目实验遵循以下原则：

- 同一组对照实验使用相同任务；
- 固定随机 seed；
- 保持 Agent 角色和任务语义一致；
- 仅切换待验证的基础设施机制；
- Provider token 与 IPC / wire 指标分开统计；
- 保存 raw、summary、environment、report；
- 对 Memory Fast Path 单独记录 hit、effective、harmful；
- 对 SharedMemory 单独验证正确性、跨进程行为和状态规模；
- 结论以保存的正式实验结果为准，不以单次 smoke demo 推广性能结论。

---

## 13. 已知边界

1. **结构化协议不保证所有消息都比文本更小。**  
   其主要价值是消息契约、路由、引用和可观测性；大对象优化依赖 `ArtifactRef` / `StateRef`。

2. **StateRef 不是完全 zero-copy。**  
   SharedMemory 避免了控制消息中反复展开数组，但当前 `resolve_array()` 仍返回独立 NumPy 数组。

3. **SharedMemory 对小状态存在固定开销。**  
   因此不能仅凭大状态实验结论推断所有状态规模都能降低时延。

4. **语义记忆命中不等于 Fast Path。**  
   普通 retrieval 只提供上下文；未经 evaluator 验证的结果不会直接跳过执行。

5. **E8 的整体收益与工作负载有关。**  
   50% exact-repeat 是实验设计的一部分，不代表任意新任务都具有同样收益。

6. **当前目标环境是单机 openEuler / Linux。**  
   项目没有宣称已经完成多机分布式调度、Kubernetes 编排或外部向量数据库部署。

---

## 14. 比赛材料

评审时建议按以下顺序查看：

```text
README.md
   ↓
docs/项目说明书.pdf
   ↓
docs/项目创新说明.pdf
   ↓
tests/evidence/
   ↓
demo/
   ↓
presentation/
```

比赛提交材料遵循匿名要求，不应在公开代码、文档、PPT、视频和截图中保留学校、指导老师或参赛人员身份信息。

---

## 15. 名称说明

作品名称：

```text
memlink
```

为保持历史工程兼容，以下内部名称继续保留：

```text
Python package: src/agentipc
CLI:            agentipc
Env prefix:     AGENTIPC_*
```

它们仅属于工程内部接口命名，不改变参赛作品名称和技术内容。
