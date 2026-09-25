# MemLink Project Vision

## 1. 项目定位

MemLink 是：

> 面向多智能体协作的低开销通信、共享状态与跨任务记忆运行时。

英文定位：

> A Low-Overhead Multi-Agent Communication & Shared-State Runtime.

MemLink 的核心不是聊天界面，也不是重新实现一个通用 Agent Framework。

Agent 是实验载体，MemLink Runtime 本身才是作品主体。

---

## 2. 项目要解决的问题

普通多 Agent 系统中，经常存在三类明显浪费。

### 2.1 重复说很多话

Agent 之间经常通过完整自然语言文本传递任务背景、长上下文、中间结果、已知信息和重复证据。

MemLink 将这一问题概括为：

> 少说。

核心机制：

```text
Structured Protocol
        +
MessagePack
        +
ResultRef
        +
real IPC
```

### 2.2 重复搬大量状态

Embedding、检索结果、中间数组和其他非文本状态如果被转成文本，或者反复跨进程序列化，会产生不必要的数据复制和通信。

MemLink 将这一问题概括为：

> 少搬。

核心机制：

```text
StateRef
    +
Shared Memory
```

### 2.3 重复做已经做过的工作

相关连续任务中，系统可能重复搜索同类证据、调用相同工具、分析已验证现象或重建已有策略。

MemLink 将这一问题概括为：

> 少做。

核心机制：

```text
Shared Memory
      ↓
Validation
      ↓
Verified Memory
      ↓
Fast Path
      ↓
Avoided Operations
```

---

## 3. 三个核心创新方向

### 3.1 Structured IPC：少说

目标：让多 Agent 的业务通信真正经过结构化协议和操作系统 IPC，而不是继续依赖隐藏的 Python 对象传递。

关键机制：

- AgentMessage
- MessagePack
- Unix Domain Socket
- correlation/message/task IDs
- ResultRef
- actual transport byte accounting

### 3.2 Shared State：少搬

目标：让 Embedding 等非文本中间状态真正实现跨进程引用，而不是将向量文本化或完整放入消息传输。

关键机制：

- StateRef
- shared-memory backend
- dtype / shape / byte size
- checksum
- owner
- generation
- lifecycle cleanup

### 3.3 Verified Memory Fast Path：少做

目标：让共享记忆不只是“检索到”，而是真的影响后续执行路径。

```text
Retrieved
    ↓
Consumed
    ↓
Validated
    ↓
Work Avoided
```

核心指标：

- memory queries
- retrieved memory IDs
- consumed memory IDs
- validated memory IDs
- avoided operations
- skipped retrieval/tool calls
- end-to-end latency

---

## 4. 项目不是什么

MemLink 不试图成为：

- 一个大而全的 Agent Framework；
- 一个新的 LangGraph；
- 一个新的 Ray；
- 一个通用向量数据库；
- 一个复杂知识图谱系统；
- 一个模型内部 latent communication 算法；
- 一个分布式云平台；
- 一个只追求漂亮 UI 的 Demo。

项目重点是：

> 在单机操作系统环境中，把多 Agent 通信、状态传递与共享记忆做成真实、可测量、可验证的运行时机制。

---

## 5. 最终用户故事

```text
User
 ↓
Planner
 ↓
Retriever
 ↓
Executor
 ↓
Reviewer
```

第一阶段：

```text
Planner 通过 Structured IPC 发送计划
                  ↓
                少说
```

第二阶段：

```text
Retriever 生成证据和 embedding
      ↓
ResultRef / StateRef
      ↓
Shared Memory
      ↓
      少搬
```

第三阶段：

```text
Reviewer 验证结论
      ↓
写入 Verified Memory
```

后续相关任务：

```text
Memory 被检索
      ↓
Memory 被消费
      ↓
通过验证
      ↓
跳过重复 retrieval / tool operation
      ↓
      少做
```

---

## 6. 最终答辩叙事

MemLink 应当能够用一句话说明：

> 小消息走结构化 IPC，大状态走共享内存，历史经验通过可验证记忆直接减少重复工作。

```text
MemLink
  │
  ├── 少说：Structured IPC
  ├── 少搬：Shared State
  └── 少做：Verified Memory Fast Path
```

checksum、heartbeat、capability、lifecycle、fault handling、checkpoint 都属于支撑机制，不应抢占核心创新叙事。

---

## 7. 设计原则

### 原则一：真实机制优先于复杂机制

真实跨进程 UDS 比复杂但只存在于 Python 内存中的协议更重要。

真实 SharedMemory 消费比复杂 latent-state 算法更重要。

真实 avoided operation 比漂亮的 memory hit rate 更重要。

### 原则二：测得到才说

不预设一定降低延迟、一定节省多少百分比、一定减少 Token，或者 Memory 一定在所有任务上有效。

### 原则三：允许负结果

```text
small payload:
inline 更快

large payload:
StateRef 更有优势
```

这是有价值的 crossover 结果。

### 原则四：公平 baseline

Text 与 Structured 必须尽可能共享模型、任务、进程拓扑、工具、记忆策略和随机种子。

### 原则五：控制复杂度

任何新功能都必须回答：

> 它是否直接增强“少说、少搬、少做”之一？

如果不能，则默认不进入核心开发范围。

---

## 8. 最终成功标准

### 通信

评委可以看到不同 Agent PID，并确认业务消息真的经过 IPC。

### 状态

评委可以看到 Producer 写 SharedMemory，Consumer 通过 StateRef 在另一个进程读取并使用。

### Memory

```text
Memory OFF:
retrieval/tool operations = N

Memory ON:
retrieval/tool operations < N
```

并能够追踪是哪条已验证 Memory 触发了 Fast Path。

### 实验

所有核心结论都能回到原始运行记录、测试、benchmark manifest 和可复现命令。

---

## 9. 项目边界

最终目标平台：

```text
openEuler 24.03-LTS-SP3
```

开发阶段主要环境：

```text
Windows + repository-local .venv
```

优先级：

```text
正确
→ 可测
→ 稳定
→ 可解释
→ 再优化
```
