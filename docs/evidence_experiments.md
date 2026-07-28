# MemLink 通信与共享记忆证据实验

## 1. 实验目的

本实验在不改变现有 Orchestrator、Agent、协议和 300 条正式 Benchmark
结果的前提下，为以下机制补充可审查证据：

- MessagePack 对同一批消息的编码体积；
- `result_ref` 对完整结果重复内联的影响；
- SemanticState 二进制状态与 `state_id` 引用的独立开销；
- SQLite Shared Memory 从检索、提供到进入证据链的实际复用过程。

新增结果只写入 `benchmarks/evidence_results/`，不会写入或覆盖
`benchmarks/results/`。运行入口还会拒绝把现有结果目录指定为输出目录。

## 2. 实验 A：上下文规模增长

### 实验组

- `text`
- `structured`
- `structured_no_result_ref`

每组使用 1x、2x、4x、8x 四种上下文规模，默认每种规模运行 10 轮，
共生成 120 条目标任务记录。

上下文由按时间顺序组织的网关、检索、生成服务和数据库故障证据组成。
扩展规模时增加确定性、带编号的故障证据片段，不使用随机无意义字符串。

### 公平性控制

- 三个实验组使用完全相同的标题、Prompt、任务主题和证据片段；
- 使用同一套生产 Fake LLM 响应逻辑和 Fake Embedding；
- 每条记录重置随机种子，并使用独立临时 SQLite、状态和指标目录；
- 关闭 Shared Memory，避免历史记忆成为混杂因素；
- structured 两组都启用 SemanticState，只改变 `result_ref` 开关；
- 失败、固定协议开销和不利结果均不得隐藏；
- JSON 与 MessagePack 始终编码同一批实际消息。

### 指标定义

| 字段 | 精确定义 |
| --- | --- |
| `utf8_payload_bytes` | 实际消息载荷中字符串值编码为 UTF-8 后的字节总和 |
| `json_bytes` | 完整实际消息集合使用紧凑 UTF-8 JSON 编码后的字节总和 |
| `msgpack_bytes` | 与 `json_bytes` 完全相同的消息集合使用 MessagePack 编码后的字节总和 |
| `text_characters` | 消息载荷字符串的 Unicode 字符总数 |
| `estimated_tokens` | 固定口径 `ceil(text_characters / 4)`，不是模型 tokenizer 结果 |
| `result_ref_count` | structured 协议中顶层 `result_ref` 非空的消息数 |
| `result_ref_payload_bytes` | 顶层和参数字段中结果引用字符串的 UTF-8 字节总和 |
| `inlined_payload_bytes` | text 完整正文，或 structured 完整结果字段的紧凑 JSON 字节 |
| `repeated_payload_bytes` | 每个确定性故障证据片段首次出现后，所有精确重复出现的 UTF-8 字节 |
| `repeated_payload_ratio` | `repeated_payload_bytes / utf8_payload_bytes` |
| `semantic_state_binary_bytes` | `state_id` 引用的 NumPy 向量原始二进制字节，不含 `.npy` 容器开销 |
| `state_reference_bytes` | 协议中所有 `state_id` 字符串的 UTF-8 字节 |
| `elapsed_ms` | Orchestrator 的本地 Agent、状态和存储总耗时，不是纯网络延迟 |

text 模式的 `msgpack_bytes` 是对同一批 text 消息做的编码体积对照，
不表示生产 text 模式实际启用了 MessagePack 传输。

## 3. 实验 B：共享记忆复用有效性

### 场景与条件

场景：

- RAG / 检索故障；
- API / 基础设施故障。

条件：

- `no_memory`：完全关闭 Shared Memory；
- `cold_memory`：空数据库直接执行目标任务，任务完成后正常写入；
- `warm_memory`：先执行同主题前置任务，再执行相关后续任务；
- `irrelevant_memory`：只执行另一主题的前置任务，再执行目标任务。

每个场景、每种条件默认运行 10 轮，共 80 条目标任务记录。
warm 和 irrelevant 条件还各执行一次前置任务，因此实际共有 120 次
Orchestrator 任务执行。

### 公平性控制

- 每个条件的每轮使用新的临时 SQLite 数据库；
- 所有目标任务使用 structured、`result_ref` 和同一 Fake 后端；
- 本实验关闭 SemanticState，以隔离关键词/标签共享记忆复用；
- 相关记忆 ID 是同轮前置任务实际写入 SQLite 的记录，不是伪造 ID；
- 无关记忆来自另一故障主题的真实前置任务；
- `retrieved_memory_ids` 和 `reused_memory_ids` 分开记录；
- 相关性由场景设置确定，不由被测 Agent 自行宣布。

### 指标定义

| 字段 | 精确定义 |
| --- | --- |
| `retrieved_memory_ids` | Orchestrator 多策略检索后去重并提供给 Agent 的记忆 ID |
| `reused_memory_ids` | Retriever 输出的 `memory:<id>` 证据所引用的 ID |
| `expected_memory_ids` | 同轮相关前置任务实际写入 SQLite 的记忆 ID |
| `irrelevant_memory_ids` | 负对照前置任务实际写入 SQLite 的无关记忆 ID |
| `relevant_memory_reused` | 预期 ID 非空且全部进入后续证据链 |
| `irrelevant_memory_reused` | 至少一个负对照 ID 进入后续证据链 |
| `memory_reuse_precision` | 相关复用 ID 数除以全部复用 ID 数；无复用时为 0 |
| `repeated_steps` | 目标 TaskPlan 与同轮前置 TaskPlan 完全相同的步骤数 |
| `avoided_steps` | 同场景 no-memory 计划步骤数减当前步骤数，下限为 0 |
| `repeated_payload_bytes` | 记忆 summary/content 在目标 LLM 输入中首次出现后的重复 UTF-8 字节 |
| `reviewer_accepted` | 整个 structured ReviewResult 是否通过 |
| `reviewer_rejected_memory` | 已检索但未进入证据链且整体审核通过的候选 ID |

当前 Reviewer 协议没有逐条记忆接受/拒绝字段，因此
`reviewer_rejected_memory` 不能解释成模型生成了逐条拒绝理由。报告不会用
`memory_hit_count` 单独证明正确复用。

## 4. 运行命令

Windows：

```powershell
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m app.benchmark.context_scaling --rounds 10

D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m app.benchmark.memory_reuse --rounds 10
```

输出已经存在时，程序默认拒绝覆盖。确认需要重跑新证据实验时，显式增加：

```text
--overwrite
```

openEuler：

```bash
/home/fjy/memlink/.venv/bin/python -m app.benchmark.context_scaling --rounds 10

/home/fjy/memlink/.venv/bin/python -m app.benchmark.memory_reuse --rounds 10
```

## 5. 输出文件

上下文增长：

- `benchmarks/evidence_results/context_scaling_raw.csv`
- `benchmarks/evidence_results/context_scaling_summary.csv`
- `benchmarks/evidence_results/context_scaling_summary.json`
- `benchmarks/evidence_results/context_scaling_report.md`

共享记忆：

- `benchmarks/evidence_results/memory_reuse_raw.csv`
- `benchmarks/evidence_results/memory_reuse_summary.csv`
- `benchmarks/evidence_results/memory_reuse_summary.json`
- `benchmarks/evidence_results/memory_reuse_report.md`

图片保存在 `benchmarks/evidence_results/figures/`，使用白色背景、
1600×900 分辨率和水平横轴标签。

## 6. 如何解读

应优先查看随上下文规模增长的斜率，而不是只看 1x 单点。在短上下文中，
structured 可能因协议字段、握手和状态引用而具有固定开销。只有原始数据
确实支持时，才能描述某项指标下降。

MessagePack 指标证明同一消息集合的编码差异，不证明当前单进程实现发生了
实际网络传输。`result_ref` 指标证明协议载荷避免了完整结果内联，不等价于
真实模型 Prompt 已按同比例下降。

共享记忆应依次检查检索 ID、进入证据链的 ID、相关性真值和 Reviewer
整体结果。命中但未引用不能算实际复用；无关记忆进入证据链应按误用记录。

## 7. 实验局限

- Fake LLM 是确定性测试替身，其计划和响应模式不能代表所有真实模型；
- 本地耗时包含 Python、SQLite、文件系统和状态保存，不是网络延迟；
- 记忆实验为隔离变量关闭了向量检索，不能证明向量召回准确率；
- Reviewer 暂无逐条记忆接受字段；
- 当前 MessagePack 是编码体积统计，并非独立进程间通信链路；
- 单轮 DeepSeek 演示只证明真实后端可运行，不能替代多轮 Benchmark。

## 8. Fake 与 DeepSeek 的边界

pytest、现有 300 条 Benchmark 和本证据实验均默认且仅使用 Fake 后端，
用于离线、确定性、可复现验证。证据实验不会读取 DeepSeek 凭据，也不会
发起网络请求。

已有 DeepSeek 验证属于真实模型可用性演示。不能把本离线协议 Benchmark
描述成 DeepSeek 性能 Benchmark，也不建议使用付费模型直接执行完整矩阵。
