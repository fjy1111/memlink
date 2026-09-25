# MemLink Claims and Acceptance Gates

## 1. 目的

本文件定义：

> MemLink 在什么条件满足后，才允许对外声称某项能力已经实现。

接口存在不等于机制完成。

测试通过不一定等于真实数据路径成立。

所有强 claim 必须由：

```text
implementation
+
test
+
observable evidence
```

共同支撑。

---

# 2. Claim：真实多进程 Agent Runtime

允许表述：

> Planner、Retriever、Executor、Reviewer 运行在独立进程中。

必须满足：

```text
[ ] four Agent worker processes exist
[ ] each has a distinct PID
[ ] PID differs from orchestrator PID
[ ] workers can start
[ ] workers can stop
[ ] no process residue after normal shutdown
[ ] worker crash is observable
```

禁止仅凭：

```text
multiprocessing module imported
```

就声称完成。

---

# 3. Claim：真实 IPC

允许表述：

> Agent 之间通过 Unix Domain Socket 进行进程间通信。

必须满足：

```text
[ ] sender and receiver are different processes
[ ] payload actually enters socket send/write
[ ] receiver actually reads payload from socket
[ ] disabling/breaking socket prevents communication
[ ] sent/received transport bytes are measured
```

禁止将：

```text
MessagePack serialized size
```

称为：

```text
actual IPC bytes
```

---

# 4. Claim：Protocol-only Data Path

允许表述：

> Agent 间业务数据只通过 MemLink 协议与引用机制传递。

必须满足：

```text
[ ] no direct Agent-to-Agent method business call
[ ] no shared Python business object bypass
[ ] Planner output reaches Retriever via transport/ref
[ ] Retriever output reaches Executor via transport/ref
[ ] Executor output reaches Reviewer via transport/ref
[ ] tests fail when protocol path is unavailable
```

允许 Runtime 内部管理对象、process handle 和 registry metadata。

禁止：

```text
protocol is traced,
but actual business object is directly passed
```

---

# 5. Claim：MessagePack 降低编码体积

允许表述：

> 对当前结构化消息，MessagePack 编码体积小于 JSON。

必须满足：

```text
[ ] identical logical message
[ ] JSON and MessagePack both measured
[ ] byte calculation is exact serialized byte length
```

这只能证明：

```text
encoding-size difference
```

不能自动证明网络吞吐改善或延迟降低。

---

# 6. Claim：ResultRef 减少大结果跨 IPC 传输

必须满足：

```text
[ ] Producer stores full result outside control message
[ ] control message contains ResultRef
[ ] Consumer resolves ResultRef
[ ] Consumer actually uses resolved result
[ ] inline baseline exists
[ ] actual transport bytes are compared
```

不能只统计 JSON field size 然后称为真实 IPC 节省。

---

# 7. Claim：共享内存非文本状态传递

允许表述：

> MemLink 通过 StateRef 和 SharedMemory 在不同 Agent 进程间传递非文本状态。

必须满足：

```text
[ ] Producer and Consumer have different PIDs
[ ] Producer writes real binary/numerical state
[ ] Producer creates StateRef
[ ] Consumer receives StateRef through protocol
[ ] Consumer attaches state using StateRef
[ ] dtype is validated
[ ] shape is validated
[ ] checksum/integrity is validated
[ ] Consumer uses the recovered state
[ ] direct ndarray/object bypass does not exist
```

负测试：

```text
[ ] missing shared memory fails
[ ] wrong checksum fails
[ ] invalid generation/ref fails where implemented
```

---

# 8. Claim：Zero-copy

默认禁止声明。

除非专门完成端到端内存复制分析。

允许优先表述：

> 使用共享内存引用避免将完整状态通过控制消息重复序列化和传输。

NumPy view 本身可不复制，不代表整个 application path 就是 zero-copy。

---

# 9. Claim：实际通信字节降低

必须比较：

```text
actual framed bytes written to transport
```

而不是只比较：

```text
character count
JSON bytes
MessagePack bytes
```

报告中应区分：

```text
logical bytes
serialized bytes
transport bytes
state bytes
```

---

# 10. Claim：Structured 模式降低 Token

必须满足：

```text
[ ] same task
[ ] same model
[ ] same relevant context policy
[ ] actual tokenizer or provider usage
```

如果只使用字符估算：

```text
estimated_token_count
```

必须明确写“估算 Token”。

---

# 11. Claim：Structured 模式延迟更低

只有 benchmark 实际支持时才允许。

必须：

```text
[ ] same process topology
[ ] same model
[ ] same task
[ ] same tools
[ ] same memory state
[ ] multiple runs
```

如果小 payload 更慢，则报告真实结果。

允许形成 crossover point，而不是强行证明所有场景更快。

---

# 12. Claim：Memory 被成功复用

不能使用：

```text
memory_hit_count > 0
```

作为充分条件。

必须区分：

```text
Retrieved
Consumed
Validated
```

至少满足：

```text
[ ] retrieved_memory_id recorded
[ ] consumed_memory_id recorded
[ ] validation result recorded
```

---

# 13. Claim：Memory 减少重复工作

必须满足：

```text
[ ] relevant sequential tasks
[ ] memory OFF baseline
[ ] memory ON comparison
[ ] same task/model/tools
[ ] verified memory consumed
[ ] one or more actual operations are skipped/reduced
[ ] avoided_operation_count > 0
```

可被避免的 operation：

```text
retrieval
tool call
planning step
evidence generation
```

必须记录：

```text
trigger_memory_id
avoided_operation_type
avoided_operation_count
```

`usage_count` 增长不等于 avoided work。

---

# 14. Claim：Memory 没有错误复用无关信息

需要 negative control。

至少：

```text
[ ] unrelated tasks exist
[ ] irrelevant/stale memory exists
[ ] retrieval and consumption separately measured
[ ] irrelevant memory does not trigger incorrect Fast Path
```

允许出现：

```text
retrieved
but rejected
```

这是正常且有价值的结果。

---

# 15. Claim：公开数据集实验无数据泄漏

必须满足：

```text
[ ] Runtime receives only runtime input
[ ] evaluation answer is not passed to Agent
[ ] supporting facts are not passed as gold labels
[ ] reference code is not passed to code Agent
[ ] hidden tests are not passed to code Agent
[ ] Gold_passage/Rationale are not silently injected
```

测试必须覆盖 `to_runtime_input()` 或等价隔离机制。

---

# 16. Claim：TopiOCQA/QReCC 是连续任务 Memory 实验

必须：

```text
[ ] sample complete conversations
[ ] preserve Turn order
[ ] group_id stable
[ ] later turns remain context-dependent
```

禁止把随机独立 turns 拼起来称为连续任务。

---

# 17. Claim：HotpotQA Retrieval Benchmark 公平

Agent 可访问：

```text
question
candidate context/documents
```

Evaluator 才能访问：

```text
answer
supporting_facts
```

禁止 Retriever 直接读取 gold supporting facts。

---

# 18. Claim：CodeAct 完成

至少需要：

```text
[ ] model/Agent generates code
[ ] generated code is executed
[ ] execution result is captured
[ ] hidden evaluation tests determine success
```

仅返回代码文本不能称为完整 CodeAct execution。

---

# 19. Claim：安全 Sandbox

默认禁止使用：

```text
secure sandbox
```

除非真正实现和验证了强隔离。

如果只使用 subprocess + timeout/RLIMIT，应准确描述为：

> lightweight restricted execution environment

或：

> subprocess-based execution isolation

---

# 20. Claim：Fault Tolerance

某个故障只有在存在对应测试后才能声称支持。

例如：

```text
partial read       -> test
oversized frame    -> test
timeout            -> test
peer crash         -> test
worker restart     -> test
checksum failure   -> test
```

没有测试的恢复路径只能称为 planned / experimental。

---

# 21. Claim：openEuler 支持

最终必须在：

```text
openEuler 24.03-LTS-SP3
```

实际完成：

```text
environment setup
dependency installation
full pytest
runtime demo
benchmark smoke
resource cleanup
```

Windows 测试成功不能替代 openEuler 实机验证。

---

# 22. Claim：稳定运行

赛题要求连续多轮稳定运行。

至少记录：

```text
task count
success count
failure count
exceptions
process residue
shared-memory residue
temporary files
database handles
```

不得只因为没有 Python exception 就称为无资源泄漏。

---

# 23. Evidence Levels

### Level 0 — Planned

```text
document only
```

不得写成已实现。

### Level 1 — Implemented

```text
code exists
```

仍不能说明真实路径已经成立。

### Level 2 — Tested

```text
focused automated tests pass
```

### Level 3 — Integrated

```text
real runtime path consumes mechanism
```

### Level 4 — Measured

```text
benchmark metrics exist
```

### Level 5 — Reproduced

```text
repeatable run / target environment evidence exists
```

高强度性能 claim 应优先达到 Level 4/5。

---

# 24. Reviewer Checklist

Reviewer Codex 应优先检查：

```text
[ ] Is the claimed mechanism on the real data path?
[ ] Is there a hidden Python-object bypass?
[ ] Is the metric measuring what its name claims?
[ ] Is the receiver actually consuming the referenced state?
[ ] Is memory actually avoiding work?
[ ] Is gold benchmark data isolated?
[ ] Are baselines fair?
[ ] Are negative cases tested?
[ ] Are resources cleaned up?
[ ] Is the wording stronger than the evidence?
```

---

# 25. Core Final Claims

MemLink 最终最希望可靠证明的只有三条：

## Claim A

> Agent 之间通过真实结构化 IPC 协作，并减少大型业务数据在控制消息中的重复传输。

## Claim B

> 非文本状态通过 StateRef 和 SharedMemory 在独立 Agent 进程之间交换和消费。

## Claim C

> 已验证共享记忆在相关连续任务中可以触发 Fast Path，并真实减少部分重复操作。

如果这三条达到高证据等级，项目主体就已经成立。
