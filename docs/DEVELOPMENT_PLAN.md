# MemLink V2 Development Plan

## 1. 开发原则

国赛阶段不再进行大规模架构扩张。

开发目标从：

```text
增加功能
```

切换为：

```text
让三个核心机制真正成立
```

三个核心机制：

```text
Structured IPC
Shared State
Verified Memory Fast Path
```

---

## 2. 开发方式

采用：

```text
一个任务
一个明确边界
一组 Acceptance Gates
一组测试
一个可提交状态
```

禁止：

```text
一次重构整个 Runtime
```

每一步都必须保持项目可运行。

---

# 3. 已完成阶段

## Task 01：Unified Benchmark Dataset Layer

状态：

```text
DONE
```

已支持：

- TopiOCQA
- QReCC
- HotpotQA
- MBPP
- HumanEval

统一为：

```text
BenchmarkCase
BenchmarkGroup
```

Task Types：

```text
conversational_qa
retrieval_qa
code_generation
```

关键保证：

- Runtime input 与 evaluation 分离；
- 防止 gold leakage；
- 连续任务按 conversation 分组；
- fixed-seed sampling；
- public dataset support。

当前测试基线：

```text
114 passed
```

具体测试数量会随着后续开发增加，不应写死到对外项目 claim 中。

---

# 4. P0：真实 Runtime 基础

P0 是国赛版本最重要的阶段。

在 P0 完成前，不优先实现高级 Memory、CodeAct 或 UI 功能。

---

## Task 02A：Worker Process

目标：实现最小独立 Worker Process。

只验证：

```text
parent process
      ↓
spawn worker
      ↓
worker has different PID
      ↓
stop
      ↓
no residual process
```

不实现：

- UDS；
- MessagePack；
- Agent business logic；
- Memory；
- StateRef。

Acceptance Gates：

```text
[ ] worker can start
[ ] worker PID != parent PID
[ ] worker can report ready
[ ] worker can stop
[ ] worker exits within timeout
[ ] no worker residue after shutdown
[ ] existing tests still pass
```

---

## Task 02B：UDS Transport + Framing

目标：建立两个独立进程之间最小 UDS 通信。

协议：

```text
uint32_be payload length
+
raw payload
```

Acceptance Gates：

```text
[ ] server accepts client
[ ] small payload delivered
[ ] partial reads handled
[ ] multiple sequential frames handled
[ ] oversized frame rejected
[ ] peer close handled
[ ] socket cleanup works
[ ] real bytes sent/received recorded
```

暂不接 AgentMessage。

---

## Task 02C：MessagePack Transport

目标：在 UDS framing 上加入 MessagePack。

Acceptance Gates：

```text
[ ] dict → MessagePack → UDS → dict
[ ] malformed MessagePack rejected
[ ] serialized bytes recorded
[ ] transport bytes recorded separately
[ ] unsupported payload produces explicit failure
```

---

## Task 02D：Minimal AgentMessage

目标：

```text
Planner Process
      ↓
AgentMessage
      ↓
UDS
      ↓
Retriever Process
```

Acceptance Gates：

```text
[ ] Planner and Retriever PIDs differ
[ ] message passes through UDS
[ ] sender/receiver/action validated
[ ] correlation_id preserved
[ ] disabling transport makes communication fail
[ ] no direct Python business object passed
```

---

## Task 02E：Four-Agent Process Runtime

扩展为：

```text
Planner
↓
Retriever
↓
Executor
↓
Reviewer
```

Acceptance Gates：

```text
[ ] four independent PIDs
[ ] startup succeeds
[ ] shutdown succeeds
[ ] full minimal control flow completes
[ ] no process leak
[ ] failures are observable
```

此阶段仍可以使用简化 fake business payload。

---

# 5. P0：ResultRef

## Task 03A：ResultStore

实现：

```text
put
get
release
delete
```

不得继续依赖 Orchestrator private dict 作为最终机制。

## Task 03B：ResultRef data path

流程：

```text
Producer
 ↓
ResultStore.put
 ↓
ResultRef
 ↓ UDS
Consumer
 ↓
ResultStore.get
```

Acceptance Gates：

```text
[ ] large result not inlined in control message
[ ] consumer resolves ResultRef
[ ] wrong ResultRef fails
[ ] reference bytes measured
[ ] inline baseline still available
```

---

# 6. P0：Shared State

## Task 04A：SharedMemory Backend

实现 NumPy ndarray → SharedMemory。

Acceptance Gates：

```text
[ ] producer creates shared state
[ ] metadata records dtype/shape/nbytes
[ ] consumer attaches from another process
[ ] restored values equal original
[ ] checksum validated
[ ] cleanup works
```

## Task 04B：StateRef

建立：

```text
state_id
backend
shm_name
nbytes
dtype
shape
checksum
owner
generation
```

控制消息只携带 StateRef。

## Task 04C：Real state consumption

必须证明：

```text
Retriever Process
      ↓
StateRef
      ↓
Executor Process
      ↓
attach
      ↓
consume ndarray
```

Acceptance Gates：

```text
[ ] no direct ndarray passed
[ ] consumer PID differs
[ ] consumer obtains only StateRef
[ ] consumer reads actual state
[ ] removing shared state causes failure
```

完成后才允许声明：

> 实现跨进程共享内存非文本状态传递。

---

# 7. P0：Fair Communication Benchmark

建立：

```text
Text / UDS
vs
Structured / UDS
```

必须保持：

- same workers；
- same process topology；
- same model；
- same tasks；
- same tools；
- same dataset manifest。

指标至少：

```text
message count
serialized bytes
actual transport bytes
state bytes
latency
```

不要保证 Structured 对小 payload 一定更快。

重点寻找：

```text
crossover point
```

---

# 8. P1：Capability Registry

建立简化 Agent Descriptor：

```text
agent_id
role
capabilities
accepted_actions
accepted_payloads
state_backends
protocol_version
process_id
endpoint
status
```

先做：

```text
declared
↓
runtime verified
```

避免复杂 service discovery。

---

# 9. P1：Verified Memory

升级 MemoryUnit。

关键新增：

```text
source_task_id
source_message_id
validation_status
source_version
source_hash
```

最低状态：

```text
candidate
verified
stale
```

Reviewer 负责从 candidate 提升到 verified。

---

# 10. P1：Memory Fast Path

目标：真实减少后续相关任务的操作。

实验：

```text
Memory OFF
vs
Memory ON without Fast Path
vs
Memory ON + Fast Path
```

记录：

```text
retrieved
consumed
validated
avoided_operations
```

Acceptance Gate：

```text
avoided_operations > 0
```

必须是真实跳过的操作。

---

# 11. P1：Public Dataset Integration

## TopiOCQA / QReCC

主要验证：

```text
long context
memory reuse
related sequential tasks
```

比较：

```text
Full Text History
vs
MemLink Memory
```

QReCC 的 `Rewrite` 可作为额外 baseline，但默认不能进入 Agent Input。

## HotpotQA

主要验证：

```text
Retriever
Evidence
ResultRef
StateRef
```

优先：

```text
distractor validation
```

## MBPP / HumanEval

主要验证：

```text
CodeAct / execution completeness
```

不是第一核心性能实验。

---

# 12. P1：Evidence Discipline

建立：

```text
docs/claim-evidence.csv
```

至少记录：

```text
claim
status
source implementation
test
benchmark run
allowed wording
forbidden wording
```

---

# 13. P1：Experiment Methodology

正式结果逐步增加：

- paired comparisons；
- fixed seed；
- stable manifest；
- multiple rounds；
- confidence intervals；
- AB/BA order when model/API variance matters。

---

# 14. P2：Checkpoint / Resume

目标：worker crash 后不用重新执行已经成功的阶段。

不是 P0。

---

# 15. P2：Memory-aware Selective Handoff

例如 verified memory 足够时：

```text
skip Retriever
```

统计：

```text
agent invocations
messages
tokens
latency
```

不实现复杂通信图学习。

---

# 16. P2：Persistent CodeAct Worker

如果一次性 subprocess 开销过大，可研究 persistent worker。

必须保留明确安全边界。

不要称普通 subprocess 为“安全沙箱”。

---

# 17. P2：System Metrics

可增加：

```text
CPU
RSS
context switches
```

eBPF 只作为可选增强。

不作为项目成功条件。

---

# 18. 明确不做

没有维护者明确指令时，不实现：

```text
Redis
Milvus
Ray dependency
LangGraph migration
Hypergraph core
Residual/VLC
ToM
Hidden-state training
Dynamic communication graph training
Kubernetes
Distributed multi-node cluster
```

---

# 19. Stop Rule

每完成一个任务：

```text
targeted tests
↓
full pytest
↓
review
↓
commit
↓
stop
```

不得因为“下一步很顺手”就继续实现后续模块。

---

# 20. 当前下一任务

当前正式下一步：

```text
Task 02A
Independent Worker Process
```

只做 Worker Process。

不要在同一任务里加入：

- UDS；
- AgentMessage；
- ResultRef；
- StateRef；
- Memory；
- UI。
