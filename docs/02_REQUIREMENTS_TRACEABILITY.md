# 02 — Requirements Traceability Matrix

本文件用于保证开发始终围绕比赛硬性要求，不被额外功能带偏。

| Req ID | 比赛要求 | AgentIPC 对应设计 | 主要代码区域 | 验收证据 |
|---|---|---|---|---|
| R01 | ≥3 Agent 协同 | 4 Agent 固定链路 | `src/agentipc/agents/`, `runtime/` | demo trace 中出现四类 Agent |
| R02 | 覆盖规划/检索/执行/总结至少3类 | Planner/Retriever/Executor/Summarizer | `agents/` | 单元测试 + demo |
| R03 | 结构化通信 | AgentEnvelope | `protocol/` | schema tests + structured trace |
| R04 | 动作/参数/结果/能力 | Envelope 中 `action/args/result/capability` | `protocol/envelope.py` | round-trip test |
| R05 | 握手/能力发现/协议映射 | CapabilityRegistry + HELLO/REGISTER/DISCOVER + TextAdapter | `protocol/registry.py`, `runtime/router.py` | registry tests |
| R06 | text 与 structured 双模式 | 同一 Envelope 内核，两种传输/渲染方式 | `protocol/text_adapter.py`, `runtime/` | A vs B |
| R07 | 非文本状态交换 | NumPy + SharedMemory + StateRef | `state/` | state round-trip；consumer 使用向量 |
| R08 | 说明生成/传递/接收/使用方式 | State 设计文档 + trace | `docs/`, `state/` | state trace + 文档 |
| R09 | 共享记忆统一单元 | MemoryRecord | `memory/models.py` | schema test |
| R10 | metadata 至少含 ID/来源/时间/主题/摘要 | MemoryRecord 强制字段 | `memory/models.py` | validation test |
| R11 | 关键词/标签/语义检索 | MemoryService hybrid retrieve | `memory/` | search tests |
| R12 | 跨 Agent / 跨任务复用 | MemoryRef + persistent SQLite | `memory/`, `runtime/` | Task N+1 hit |
| R13 | 至少2组关联连续任务 | Knowledge Chain + CodeAct Chain | `tests/scenarios/` | 2×10 轮结果 |
| R14 | 减少重复计算 | Memory 命中后跳过/减少重复检索或工具调用 | `runtime/`, `evaluation/` | repeated work 指标 |
| R15 | 消息次数 | MetricsCollector | `evaluation/metrics.py` | summary.json |
| R16 | 文本 token/字符开销 | char 必选，token 可选 | `evaluation/` | summary.json |
| R17 | 非文本传递次数和规模 | state_transfer_count/state_bytes | `evaluation/` | summary.json |
| R18 | 单任务总耗时 | latency_ms | `evaluation/` | raw results |
| R19 | 共享记忆命中率 | retrieved/used/effective | `memory/`, `evaluation/` | report |
| R20 | 整体性能提升 | derived metrics | `evaluation/report.py` | A/B/C/D report |
| R21 | 多 Agent runtime | Orchestrator/Router/Context | `runtime/` | integration tests |
| R22 | 协议解析与调度 | Protocol + Router | `protocol/`, `runtime/` | integration tests |
| R23 | 状态交换模块 | StateHub | `state/` | state tests |
| R24 | 共享记忆模块 | MemoryService | `memory/` | memory tests |
| R25 | 评测模块 | BenchmarkRunner | `evaluation/` | benchmark output |
| R26 | 稳定执行≥10轮 | 每组连续任务 10 轮以上 | `tests/scenarios/` | stability run |
| R27 | CodeAct 鼓励项 | RestrictedPythonRunner | `sandbox/`, `agents/executor.py` | codeact scenario |
| R28 | openEuler 24.03-LTS-SP3 | 安装/验证脚本 | `tests/scripts/` | openEuler run log |
| R29 | 完整源码/设计/部署/实验/视频 | 交付清单 | `docs/` | final checklist |

## 使用规则

- 每完成一个 Development Task，只允许把其明确支撑的 Req 标为部分完成。
- 只有存在可运行证据时才可标为完成。
- README 中的声明必须能回链到本矩阵中的具体代码和证据。
