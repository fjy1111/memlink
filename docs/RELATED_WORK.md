# MemLink Related Work and Design References

## 1. 目的

本文件记录 MemLink 国赛设计阶段研究过的公开项目，以及从中学习到的工程思想。

目的不是复制其他项目实现。

基本原则：

> 学习公开设计思想，独立实现 MemLink 自己的数据结构、运行时、测试和实验。

禁止：

- 大段复制源代码；
- 原样复制 schema；
- 原样复制文档；
- 把竞品创新直接改名后作为 MemLink 创新。

---

# 2. 同赛题项目

## 2.1 tkj-lp/low-cost-mult-agent-memory

研究重点：

- 多 Agent 协作；
- Hidden State；
- Hypergraph Memory；
- CodeAct；
- 多种 baseline；
- public dataset；
- memory evaluation。

值得学习：

### 实验广度

MemLink 从中学习：

- 不只依赖自制任务；
- 使用公开 benchmark；
- 增加跨模型验证；
- 增加强于简单 text baseline 的比较方法。

### Memory 评价

值得借鉴的思想：

```text
Retrieved
→ Used
→ Validated
```

MemLink进一步扩展为：

```text
Retrieved
→ Consumed
→ Validated
→ Work Avoided
```

### 不采用

MemLink 不将以下机制作为自己的核心：

- LangGraph shared state；
- Hypergraph Memory；
- Hidden State 主线；
- 与该项目相同的内部 schema。

MemLink 的主线是：

```text
multi-process
IPC
shared state
verified memory fast path
```

---

## 2.2 yangchunwanwusheng/synapse

研究重点：

- memory-conditioned communication；
- residual state；
- verified lossy communication；
- Unix Domain Socket；
- transport accounting；
- fault tests；
- claim-evidence discipline。

值得学习：

### Logical bytes 与 Transport bytes 分离

不能把：

```text
MessagePack serialized bytes
```

直接等同于：

```text
actual IPC bytes
```

MemLink V2 要分别记录：

```text
logical payload bytes
serialized bytes
actual socket transport bytes
```

### Fault testing

通信系统不能只测试 happy path。

MemLink 应逐步增加：

- partial read；
- oversized frame；
- timeout；
- worker crash；
- invalid payload。

### Claim-Evidence Discipline

任何强结论都要有：

```text
claim
implementation
test
run
allowed wording
```

### 不采用

MemLink 不采用 SYNAPSE 的核心算法：

- ToM prediction；
- residual coding；
- VLC；
- Pi plugin 路线。

---

# 3. 通用系统项目

## 3.1 Ray

仓库：

```text
ray-project/ray
```

研究重点：

- ObjectRef；
- shared-memory object store；
- object lifecycle；
- reference counting；
- object spilling。

值得学习：

```text
ResultRef
StateRef
```

以及：

```text
put
get
acquire
release
cleanup
```

MemLink只实现比赛所需的精简版本。

### 不采用

MemLink 不引入 Ray 作为依赖，也不实现完整 Ray scheduler、cluster、distributed object store 或 production spill system。

---

## 3.2 Microsoft AutoGen

仓库：

```text
microsoft/autogen
```

研究重点：

- AgentRuntime；
- message envelope；
- send / publish；
- local/remote runtime distinction；
- remote Agent access restrictions。

重要启发：

> Agent 间通信应通过 Runtime abstraction，而不是获取对方对象后直接调用方法。

MemLink 因此要求：

```text
no direct Python-object business bypass
```

不把 MemLink 迁移为 AutoGen 应用。

---

## 3.3 A2A

仓库：

```text
a2aproject/A2A
```

研究重点：

- Agent Card；
- capabilities；
- skills；
- Message / Task / Artifact distinction。

值得学习：

```text
agent_id
role
capabilities
accepted_actions
accepted_payloads
protocol_version
endpoint
status
```

Message 与 Artifact 分离进一步强化了：

```text
AgentMessage
ResultRef
StateRef
```

不复制完整 A2A 网络协议。

---

## 3.4 LangGraph

仓库：

```text
langchain-ai/langgraph
```

研究重点：

- checkpoint；
- persistence；
- resume；
- pending writes。

值得学习：

```text
Task checkpoint
Crash resume
```

当前定位：

```text
P2 / late P1
```

不是 P0。

---

# 4. Memory 项目

## 4.1 A-MEM

仓库：

```text
agiresearch/A-mem
```

研究重点：

- structured memory；
- links；
- memory evolution；
- semantic retrieval。

值得学习：

```text
candidate
verified
stale
superseded
```

MemLink 可以采用简单生命周期，而不是复制完整 graph memory。

---

## 4.2 MemOS / MemTensor

研究重点：

- memory as a system service；
- memory sharing；
- memory scope；
- feedback；
- lifecycle。

值得学习：

```text
task
agent
team
global
```

核心比赛版本优先：

```text
task
team
```

---

## 4.3 Mem0

仓库：

```text
mem0ai/mem0
```

研究重点：

- extraction；
- hybrid retrieval；
- user/session/agent memory；
- temporal metadata。

值得学习：

```text
keyword
tag
semantic
```

不引入 Mem0 服务本身作为核心依赖。

---

## 4.4 GateMem

研究重点：

- shared-memory governance；
- multi-principal memory；
- utility；
- forgetting；
- access control。

重要启发：

> Shared Memory 不意味着所有 Agent 永远可以读取所有记忆。

MemLink 后期可支持：

```text
scope
owner_agent
allowed_roles
deleted_at
```

但权限治理不是当前主创新。

---

# 5. Communication Optimization Research

## 5.1 AgentPrune

仓库：

```text
yanweiyue/AgentPrune
```

研究重点：

- redundant communication；
- selective communication；
- topology pruning。

值得学习：

并非每个任务都需要调用所有 Agent。

MemLink 未来可实现：

```text
Memory-aware Selective Handoff
```

例如已有 verified memory 时：

```text
skip Retriever
```

当前定位：

```text
P2
```

---

## 5.2 MOC

仓库：

```text
yao-guan/MOC
```

研究重点：

- multi-order communication；
- communication topology；
- multi-hop exchange。

启发：

通信拓扑也可以作为 benchmark 变量。

当前不实现动态 topology optimization。

---

## 5.3 Interlat

研究方向：

- latent communication；
- hidden-state communication between LLM agents。

MemLink 与其定位不同：

```text
Interlat:
model-internal latent communication

MemLink:
black-box-model-compatible
system-level StateRef + SharedMemory
```

MemLink 不依赖修改模型内部结构。

---

# 6. Messaging Systems

## 6.1 ZeroMQ / libzmq

仓库：

```text
zeromq/libzmq
```

研究重点：

- async messaging；
- queue；
- backpressure；
- heartbeat；
- delivery patterns。

值得学习：

```text
mailbox queue
max queue size
heartbeat
delivery states
```

可能的 delivery lifecycle：

```text
CREATED
QUEUED
SENT
RECEIVED
PROCESSING
COMPLETED
FAILED
```

当前不需要为了这些模式引入 pyzmq。

---

# 7. 其他 Agent Framework

## MetaGPT

值得学习：

- message provenance；
- sender / receiver；
- cause/action fields。

## AgentScope

值得学习：

- typed messages；
- middleware；
- observability。

这些项目作为一般性参考，不是 MemLink 的实现依赖。

---

# 8. MemLink 的独立技术路线

经过相关工作研究后，MemLink 最终选择：

```text
Protocol-only Multi-process Runtime
            +
Ref-based Shared State Data Plane
            +
Verified Memory Fast Path
```

三个核心点：

```text
少说
Structured IPC

少搬
StateRef + SharedMemory

少做
Verified Memory Fast Path
```

---

# 9. 不进入核心开发范围的方向

除非维护者明确批准，否则不引入：

```text
Hypergraph Memory
Residual / VLC
ToM Prediction
Hidden-state training
Dynamic communication graph learning
Redis
Milvus
Ray runtime dependency
LangGraph migration
Kubernetes
Distributed cluster scheduler
```

---

# 10. 原创性原则

所有相关项目只作为：

```text
design reference
experiment reference
engineering reference
```

MemLink 必须：

- 使用自己的 schema；
- 使用自己的模块边界；
- 使用自己的测试；
- 使用自己的 benchmark implementation；
- 使用自己的文档语言；
- 对借鉴来源进行公开说明；
- 不夸大原创范围。

最终创新重点不在“首次提出所有底层概念”，而在于：

> 将真实多进程 Agent IPC、引用式共享状态和可验证跨任务 Memory Fast Path 组合成面向该赛题的可运行系统，并建立相应的可观测、可消融和可复现实验证据。
