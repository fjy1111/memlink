# memlink

> 面向多智能体协作的低开销通信、非文本状态传递与共享记忆运行时

**memlink** 是面向 openEuler / 通用 Linux 环境的多智能体协作原型系统，聚焦多 Agent 协作中的三个系统层问题：**通信开销、非文本中间状态交换、跨任务记忆复用**。

> 说明：参赛作品名称为 **memlink**；仓库内部 Python 包名与 CLI 名称沿用早期工程名 `agentipc`。

本项目不是通用 Agent 编排框架，而是围绕比赛赛题要求，提供一套可运行、可验证、可复现的系统层机制与实验环境。

---

## 1. 项目简介

传统多 Agent 系统通常依赖自然语言长文本在 Agent 之间传递上下文、中间状态和历史结果，容易带来以下问题：

- **通信冗余**：重复上下文和大对象被反复展开到消息中；
- **状态文本化开销**：数值向量、数组等中间状态需要在内部表示与文本 / JSON 之间反复转换；
- **重复计算**：后续任务无法安全复用已经验证过的历史结果；
- **实验难复现**：缺少统一协议、固定任务条件、可追踪指标与运行证据。

memlink 从协议通信、状态交换、对象引用、共享记忆和评测追踪几个层面提供统一运行时，并保留纯文本基线用于对照实验。

---

## 2. 应用场景

1. **多 Agent 协作任务**：由 Planner、Retriever、Executor、Summarizer 等角色协同完成规划、检索、执行与总结。
2. **连续知识任务**：在多轮连续任务中保存 Evidence / Experience / Result，并在后续任务中检索和复用历史记忆。
3. **CodeAct / 工具执行任务**：支持受限 Python 执行与结构化工具调用结果返回，用于验证工具执行链路和重复工作开销。
4. **非文本状态交换**：面向 NumPy 数组、计划向量等中间状态，通过 `StateRef + SharedMemory` 避免在控制消息中完整展开状态数据。
5. **多 Agent 系统实验与评测**：支持 Text Baseline、Structured Protocol、Structured + State、Structured + State + Memory 四组模式，在统一任务条件下比较通信开销、调用次数、状态交换、记忆命中、时延和任务正确性。

---

## 3. 主要功能

### 3.1 四 Agent 协作链路

- **Planner**：任务规划与分解；
- **Retriever**：信息检索与证据获取；
- **Executor**：工具 / 代码执行与状态处理；
- **Summarizer**：结果汇总与最终答案生成。

```text
User Task
   ↓
Planner
   ↓
Retriever
   ↓
Executor
   ↓
Summarizer
   ↓
Final Result
```

### 3.2 结构化通信协议

系统使用统一结构化消息模型表达 Agent 间交互，核心能力包括：

- `AgentEnvelope` 统一消息数据契约；
- 动作、参数、结果、能力和引用字段标准化；
- HELLO / REGISTER / DISCOVER 等握手与能力发现；
- ProtocolCodec 编解码与协议路由；
- 结构化字段校验、运行追踪和可观测性。

结构化协议首先解决**协作语义标准化**问题；对于较大的对象，通过 `ArtifactRef` 仅在控制链路传递引用，减少大对象重复展开。

### 3.3 ArtifactRef 对象引用

大对象由 `ArtifactStore` 独立保存，Agent 消息只传递 `ArtifactRef`：

```text
Large Object
   ↓
ArtifactStore
   ↓
ArtifactRef
   ↓
AgentEnvelope
```

### 3.4 StateRef + SharedMemory 非文本状态交换

```text
NumPy State
   ↓
StateHub.put_array(...)
   ↓
SharedMemory / inproc
   ↓
StateRef
   ↓
AgentEnvelope
   ↓
StateHub.resolve_array(...)
```

`StateRef` 可携带 URI、shape、dtype、nbytes、checksum 等元数据。接收方按引用恢复并校验状态，再参与后续检索或计算。

### 3.5 共享记忆与安全复用

`MemoryService` 用于保存跨任务的 Evidence、Experience、Result、摘要和任务结论，并支持关键词、标签、语义相似度和混合检索。

系统将“**检索到相关记忆**”与“**允许直接复用结果**”分离。只有满足严格条件的历史 RESULT 才可进入 `Validated Memory Fast Path`，例如：

- Exact Task Match；
- RESULT 类型记忆；
- evaluator 已验证；
- 答案与执行记录完整。

不满足条件时仍执行正常 Agent 链路，避免相似任务误复用。

### 3.6 Benchmark 与 Dashboard

系统提供：

- A/B/C/D 对照实验；
- 固定 seed 的可复现实验；
- raw / summary / environment / report 等结果文件；
- Agent Timeline；
- 通信与调用指标；
- Non-text State Exchange 证据；
- Shared Memory / Fast Path 证据；
- 本地 Dashboard 展示。

---

## 4. 实验模式

| 模式 | 名称 | 说明 |
| --- | --- | --- |
| A | Text Baseline | 纯文本协作基线 |
| B | Structured Protocol | 启用结构化协议 |
| C | Structured + State | 结构化协议 + StateRef 状态交换 |
| D | Structured + State + Memory | 完整机制组合，加入共享记忆与复用 |

正式实验与验证材料位于 `tests/`、`tests/evidence/`、`artifacts/` 及相关结果目录中。

---

## 5. 系统环境

### 5.1 推荐环境

- **操作系统**：openEuler 24.03-LTS-SP3
- **兼容环境**：通用 Linux
- **Python**：>= 3.10
- **Shell**：Bash
- **运行方式**：Python 虚拟环境 + editable install

项目可在 Windows 环境进行开发调试，但比赛复现与正式验证以 openEuler / Linux 路径为准。

### 5.2 核心依赖

基础依赖：

- `pydantic >= 2.0, < 3.0`
- `numpy >= 1.24`
- `psutil >= 5.9`
- `PyYAML >= 6.0`

开发与测试：

- `pytest >= 7.4`
- `wheel >= 0.41`

Dashboard：

- `fastapi >= 0.115, < 1.0`
- `uvicorn >= 0.30, < 1.0`
- `httpx >= 0.27, < 1.0`

可选能力：

- OpenAI-compatible provider
- sentence-transformers
- tiktoken

---

## 6. 获取代码

```bash
git clone https://github.com/fjy1111/AgentIPC.git
cd AgentIPC
git checkout master
```

比赛提交与复现请以 **`master` 分支**为准。

---

## 7. 构建与安装

### 7.1 推荐：一键安装

```bash
bash scripts/install.sh
```

脚本会检查 Python 版本、创建或复用 `.venv`、安装项目及 `dev,dashboard` 依赖，并安装 `agentipc` CLI。

安装完成后：

```bash
source .venv/bin/activate
agentipc version
```

### 7.2 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,dashboard]"
```

---

## 8. 配置

仓库提供 `.env.example` 作为配置示例。

```bash
export AGENTIPC_PYTHON=python3
export AGENTIPC_VENV_DIR=.venv
export AGENTIPC_BENCHMARK_PROVIDER=mock
export AGENTIPC_BENCHMARK_SEED=42
export AGENTIPC_BENCHMARK_REPEAT=3
export AGENTIPC_RESULTS_ROOT=results
```

如需使用 OpenAI-compatible provider，可参考 `.env.example` 中的：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
AGENTIPC_LLM_MODEL
AGENTIPC_EMBEDDING_MODEL
AGENTIPC_EMBEDDING_DIM
```

> 不要将真实 API Key 或 `.env` 文件提交到仓库。

---

## 9. 运行方法

### 9.1 环境自检

```bash
agentipc doctor
```

机器可读输出：

```bash
agentipc doctor --json
```

### 9.2 离线 Demo

```bash
agentipc demo --provider mock
```

### 9.3 A/B/C/D Benchmark

```bash
agentipc benchmark   --suite smoke   --repeat 3   --seed 42   --provider mock   --results-root results
```

也可以使用：

```bash
bash scripts/run_benchmark.sh
```

### 9.4 连续任务场景

知识任务：

```bash
agentipc run-scenario knowledge   --provider mock   --seed 42   --results-root results   --scenario-root scenarios
```

CodeAct 任务：

```bash
agentipc run-scenario codeact   --provider mock   --seed 42   --results-root results   --scenario-root scenarios
```

### 9.5 Dashboard

```bash
agentipc dashboard   --host 0.0.0.0   --port 8000   --results-dir results
```

浏览器访问：

```text
http://127.0.0.1:8000/
```

---

## 10. 测试方法

### 10.1 完整测试

```bash
bash scripts/run_tests.sh
```

或：

```bash
python -m pytest -q
```

### 10.2 指定测试

```bash
bash scripts/run_tests.sh tests/state
bash scripts/run_tests.sh tests/memory
bash scripts/run_tests.sh tests/protocol
```

### 10.3 openEuler 一键验收

```bash
bash scripts/verify_openeuler.sh
```

验证流程：

```text
openEuler environment check
        ↓
agentipc doctor
        ↓
pytest
        ↓
offline demo
        ↓
benchmark
        ↓
output validation
```

### 10.4 安装包 Smoke Test

```bash
bash scripts/package_smoke.sh
```

---

## 11. 项目目录

```text
.
├── README.md                       项目总说明
├── pyproject.toml                  Python 项目与依赖配置
├── .env.example                    环境变量示例
├── configs/                        默认配置
├── src/agentipc/                   核心源代码
│   ├── agents/                     Planner / Retriever / Executor / Summarizer
│   ├── artifacts/                  ArtifactStore / ArtifactRef
│   ├── evaluation/                 指标、追踪与评测
│   ├── memory/                     MemoryService
│   ├── protocol/                   AgentEnvelope / Codec / Router
│   ├── providers/                  LLM / Embedding Provider
│   ├── runtime/                    多 Agent 运行时
│   ├── sandbox/                    CodeAct 受限执行
│   └── state/                      StateHub / StateRef / SharedMemory
├── scenarios/                      连续 Knowledge / CodeAct 场景
├── dashboard/                      Dashboard 前端资源
├── scripts/                        安装、测试、Benchmark、openEuler 验证脚本
├── tests/                          单元、集成与回归测试
│   └── evidence/                   正式实验与验证证据
├── artifacts/                      冻结实验产物 / 大对象证据
├── docs/                           设计文档与比赛提交文档
├── demo/                           决赛可验证演示材料
└── presentation/                   决赛答辩 PPT 与演示视频
```

---

## 12. 比赛交付材料

```text
docs/
├── 项目说明书.pdf
├── 项目创新说明.pdf
├── 成员分工及主要贡献说明.pdf
└── 人工智能及第三方工具使用说明.pdf

demo/
└── README.md / 可验证演示交付物

presentation/
├── 决赛现场演示PPT
└── 决赛演示视频

项目根目录/
└── 作品原创承诺书.pdf
```

正式提交内容遵循匿名化要求，不在代码、文档、PPT、视频和截图中包含可识别的参赛单位、指导教师或参赛成员身份信息。

---

## 13. 结果与复现说明

为保证实验可复现，项目采用以下原则：

- 相同任务条件；
- 固定随机种子；
- 相同 Agent 角色与执行逻辑；
- A/B/C/D 仅切换对应机制；
- 保存 raw result、summary、environment 和 report；
- 保存正式实验与验证证据；
- 区分控制链路指标、Provider token 和端到端时延。

正式实验数据和图表应以仓库中的冻结实验结果和项目说明书为准。

---

## 14. 已知限制

1. **当前比赛验收 CLI 的离线复现路径以 `mock` provider 为主。**  
   该路径用于保证无外部网络依赖情况下的确定性复现。真实模型 / OpenAI-compatible provider 需要额外配置。

2. **StateRef 并非完全 zero-copy。**  
   当前 SharedMemory 路径在 `resolve` 后返回独立 NumPy 数组副本，因此项目不宣称完全零拷贝。

3. **SharedMemory 存在固定管理开销。**  
   对很小的数值状态，共享内存创建、映射和管理开销可能高于直接物化；状态规模增大后收益更明显。

4. **Memory Fast Path 采用严格复用条件。**  
   普通语义检索命中不会直接跳过执行；只有满足 exact task match、RESULT、evaluator validated 等条件的历史结果才允许进入 Fast Path。

5. **当前实现面向单机 openEuler / Linux 环境。**  
   暂未实现多机分布式运行、Kubernetes 编排或外部 Redis / 向量数据库依赖。

6. **实验结果不应泛化为所有未知任务的固定收益。**  
   不同负载、状态规模、任务重复比例和模型配置会影响通信、调用和时延收益。

---

## 15. 快速复现

```bash
git checkout master

bash scripts/install.sh
source .venv/bin/activate

agentipc doctor
agentipc demo --provider mock

bash scripts/run_tests.sh

agentipc benchmark   --suite smoke   --repeat 1   --seed 42   --provider mock   --results-root results

agentipc dashboard   --host 0.0.0.0   --port 8000   --results-dir results
```

openEuler 环境下推荐最终执行：

```bash
bash scripts/verify_openeuler.sh
```

---

## 16. 文档索引

比赛评审时建议优先阅读：

1. `README.md`
2. `docs/项目说明书.pdf`
3. `docs/项目创新说明.pdf`
4. `demo/`
5. `presentation/`

---

## 17. 名称说明

参赛作品正式名称为：

**memlink**

仓库历史名称、Python 包名和命令行入口仍沿用：

```text
AgentIPC
agentipc
src/agentipc
```

该命名差异仅为历史工程兼容考虑，不影响项目功能、实验结果与复现流程。
