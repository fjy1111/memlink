# MemLink V2 Architecture

## 1. 文档状态

本文件描述 MemLink 国赛目标架构。

它是目标架构，不代表所有模块当前已经实现。

任何文档或代码不得因为目标架构存在，就提前声称对应机制已经完成。

实际完成情况以代码、测试和 `CLAIMS_AND_GATES.md` 为准。

---

## 2. 总体架构

```text
                         MemLink Runtime
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
   Process Manager        Agent Registry         Task Manager
   lifecycle / PID        capability/probe       task lifecycle
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                         CONTROL PLANE
                                │
                   UDS + MessagePack + Framing
                                │
       Planner Proc → Retriever Proc → Executor Proc → Reviewer Proc
                                │
                         DATA PLANE
                                │
                         Payload Router
                    ┌───────────┼───────────┐
                    │           │           │
                  Inline     ResultRef    StateRef
                                │           │
                          ResultStore    ObjectStore
                                            │
                                  SharedMemoryBackend
                                            │
                                      File fallback
                                │
                         MEMORY PLANE
                                │
                         Shared Memory Store
                                │
             Candidate → Validated → Verified → Fast Path
                                │
                         EVIDENCE PLANE
                                │
        IPC bytes / state bytes / tokens / latency / memory reuse
```

---

## 3. Agent Processes

最终运行时包含四个主要 Agent：

```text
Planner
Retriever
Executor
Reviewer
```

每个 Agent 最终必须运行在独立操作系统进程中。

必须能够观测：

```text
planner_pid
retriever_pid
executor_pid
reviewer_pid
```

### 3.1 Planner

职责：

- 任务分解；
- 规划执行步骤；
- 指定所需能力。

禁止：

- 直接执行外部工具；
- 直接访问其他 Agent Python 对象。

### 3.2 Retriever

职责：

- 查询证据；
- 生成结构化 Evidence；
- 生成需要的语义向量或中间状态；
- 将大结果写入 ResultStore；
- 将非文本状态写入 State Store。

### 3.3 Executor

职责：

- 消费 Plan / Evidence / StateRef；
- 执行允许的工具；
- 产生结构化执行结果。

### 3.4 Reviewer

职责：

- 检验证据；
- 检查执行结果；
- 判断是否接受输出；
- 判断哪些经验可以进入 Verified Memory。

---

## 4. Process Manager

负责：

- worker spawn；
- PID 跟踪；
- worker startup；
- worker shutdown；
- crash detection；
- heartbeat；
- cleanup。

P0 最低能力：

```text
start
stop
pid
health
cleanup
```

不要在 P0 中实现复杂 distributed scheduler。

---

## 5. Control Plane

控制平面只负责：

- 指令；
- 引用；
- 状态；
- 错误；
- 生命周期。

默认传输：

```text
Unix Domain Socket
```

默认编码：

```text
MessagePack
```

---

## 6. UDS Framing

目标 framing：

```text
uint32_be payload_length
        +
MessagePack payload
```

要求：

- 有最大 frame 大小；
- 拒绝超长 frame；
- 正确处理 partial read；
- 正确处理 peer close；
- malformed MessagePack 返回明确错误；
- 不允许把 socket read 等价为一次完整 message read。

---

## 7. AgentMessage

控制消息至少包含：

```text
protocol_version
message_id
task_id
correlation_id
parent_message_id

sender
receiver
action

parameters

result_refs
state_refs

capability_required

status
error_code

created_at
```

控制消息应保持小型化。

禁止默认把大型 evidence、embedding 或完整执行结果内联进去。

---

## 8. Agent Descriptor / Capability Registry

每个 Agent 可声明：

```text
agent_id
role
capabilities
accepted_actions
accepted_payloads
state_backends
max_inline_bytes
protocol_version
process_id
endpoint
status
last_heartbeat
```

能力发现采用：

```text
declared
   ↓
runtime probe
   ↓
verified
```

P0 可先实现精简版本。

---

## 9. Payload Routing

最终目标：

```text
small payload
    ↓
inline

medium structured result
    ↓
ResultRef

large / numerical state
    ↓
StateRef
```

早期阶段允许固定策略，而不是立即实现复杂自适应算法。

例如：

```text
control metadata -> inline
large evidence   -> ResultRef
embedding        -> StateRef
```

只有在 benchmark 证明阈值有意义后，才实现自动 payload threshold。

---

## 10. ResultRef

ResultRef 用于引用大型结构化结果。

目标 URI 示例：

```text
ml://result/<result_id>
```

ResultStore 最低接口：

```text
put
get
release
delete
```

禁止继续使用 Orchestrator 私有 Python dict 作为最终 V2 的唯一 result-ref 机制。

---

## 11. StateRef

StateRef 用于非文本状态。

至少包含：

```text
state_id
backend
shm_name
offset
nbytes
dtype
shape
checksum
owner
generation
created_at
```

可选：

```text
expires_at
```

Consumer 必须依据 StateRef 恢复真实 ndarray/state。

---

## 12. SharedMemory State Store

主要后端：

```text
multiprocessing.shared_memory
```

Producer：

```text
numpy ndarray
    ↓
SharedMemory
    ↓
StateRef
```

Consumer：

```text
StateRef
    ↓
attach
    ↓
validate
    ↓
numpy view/copy according to implementation
    ↓
consume
```

不要在没有实验证据前对整个应用链路声称“zero-copy”。

更准确的表述应是：

> 使用共享内存引用避免将完整状态通过控制消息重复序列化和传输。

---

## 13. State Lifecycle

最低生命周期：

```text
create
attach/acquire
read
release
cleanup
```

P0 可以由 Runtime/Broker 统一负责最终 unlink。

不要为了实现复杂引用计数阻塞核心开发。

如实现 refcount，必须有明确测试。

---

## 14. Result / State Fallback

理想状态：

```text
SharedMemory
     ↓ failure
File/ResultStore fallback
     ↓ failure
explicit error
```

禁止 silent fallback 后仍把实验记录为 SharedMemory 成功。

Metrics 必须能够记录实际使用的 backend。

---

## 15. Memory Plane

MemoryUnit 建议包含：

```text
memory_id
type

source_agent
source_task_id
source_message_id

scope
owner_agent

created_at

topic
summary
content
tags
confidence

validation_status

source_version
source_hash

related_memory_ids
superseded_by

usage_count
successful_reuse_count
```

P0/P1 不要求每个字段立即完整实现。

---

## 16. Memory Lifecycle

目标状态：

```text
candidate
verified
stale
superseded
rejected
```

最重要的转换：

```text
Agent produces candidate
        ↓
Reviewer validates
        ↓
verified memory
        ↓
eligible for Fast Path
```

未经验证的 Memory 默认不得直接触发高风险 Fast Path。

---

## 17. Memory Scope

建议支持：

```text
task
session
agent
team
global
```

国赛核心至少需要：

```text
task
team
```

不把复杂权限治理作为主线。

---

## 18. Memory Fast Path

Fast Path 的目标不是提高 `memory_hit_count`。

而是：

```text
related task
    ↓
retrieve verified memory
    ↓
consume memory
    ↓
validate applicability
    ↓
skip/reduce actual operation
```

可跳过的操作例如：

- 重复 retrieval；
- 重复 tool call；
- 已验证的某一步规划；
- 重复证据生成。

必须记录：

```text
avoided_operation_type
avoided_operation_count
trigger_memory_id
```

---

## 19. Benchmark Dataset Layer

公开 benchmark 已统一为三种 TaskType：

```text
CONVERSATIONAL_QA
RETRIEVAL_QA
CODE_GENERATION
```

数据集：

```text
TopiOCQA
QReCC
HotpotQA
MBPP
HumanEval
```

数据流：

```text
Raw Dataset
    ↓
Dataset Adapter
    ↓
BenchmarkCase / BenchmarkGroup
    ↓
Benchmark Runner
```

Runtime 只能接触 Runtime Input。

不得访问 Evaluation Gold。

---

## 20. Benchmark Responsibilities

### TopiOCQA / QReCC

主要验证：

```text
Shared Memory
Memory Fast Path
long-history communication
```

必须按照完整 conversation 抽样。

### HotpotQA

主要验证：

```text
Retriever
Evidence
ResultRef
StateRef
Shared Memory
```

优先使用 distractor split，而不是构建完整 Wikipedia 检索系统。

### MBPP / HumanEval

主要验证：

```text
Executor
CodeAct
multi-agent system completeness
```

CodeAct 不是当前最高优先级创新。

---

## 21. Fair Text vs Structured Comparison

目标公平条件：

```text
same model
same task
same workers
same UDS
same tools
same memory policy
same dataset manifest
same seed
```

Text：

```text
natural-language payload
```

Structured：

```text
AgentMessage
ResultRef
StateRef
```

不能让 Text 使用同进程，而 Structured 使用多进程，再直接把所有 latency 差异归因于协议。

---

## 22. Metrics

通信：

```text
message_count
actual_socket_payload_bytes
framed_transport_bytes
serialization_bytes
control_bytes
result_ref_bytes
```

状态：

```text
state_transfer_count
state_binary_bytes
state_reference_bytes
backend
attach_latency
```

模型：

```text
prompt_tokens
completion_tokens
total_tokens
```

如 API 不提供真实 Token，可记录估算值，但必须标明：

```text
estimated
```

Memory：

```text
memory_queries
memory_retrieved
memory_consumed
memory_validated
memory_fast_path_count
avoided_operations
```

延迟：

```text
queue
serialize
send
receive
decode
agent_processing
end_to_end
```

P0 不要求第一天全部实现，但最终指标必须明确语义。

---

## 23. Failure Tests

核心 Transport 最终需要覆盖：

- partial frame；
- oversized frame；
- invalid MessagePack；
- unsupported protocol version；
- missing receiver；
- timeout；
- peer crash；
- concurrent send；
- worker crash；
- restart；
- missing StateRef target；
- checksum mismatch。

不要把所有 fault tests 放进第一个 Runtime task。

分阶段实现。

---

## 24. UI

UI 只负责可观测性。

最终优先四页：

```text
Runtime
Trace
Memory
Benchmark
```

### Runtime

展示：

- Agent status
- PID
- endpoint
- UDS
- SharedMemory backend

### Trace

展示：

- sender
- receiver
- action
- payload type
- bytes
- latency

### Memory

展示：

```text
Retrieved
Consumed
Validated
Fast Path
Avoided
```

### Benchmark

展示：

```text
Text
vs
Structured
vs
ablations
```

不要因为 UI 重构拖慢核心 Runtime。

---

## 25. Platform

开发：

```text
Windows
repository-local .venv
```

最终目标：

```text
openEuler 24.03-LTS-SP3
```

路径和实现不得依赖 Windows 绝对路径。

---

## 26. Architecture Priority

### P0

```text
real worker processes
UDS
framing
MessagePack
protocol-only path
ResultRef
StateRef
SharedMemory
actual IPC accounting
fair baseline
core tests
```

### P1

```text
capability descriptor
Verified Memory
Memory Fast Path
memory lifecycle
public benchmark integration
claim-evidence
paired statistics
```

### P2

```text
checkpoint/resume
selective handoff
persistent CodeAct worker
CPU/RSS analysis
advanced fault recovery
eBPF
```

P2 must not block P0/P1 completion.
