# 03 — Fine-Grained Development Plan

> 核心规则：**一个实现 GPT 一次只领取一个 Task ID。**
>
> 每个任务尽量只完成一个明确行为，并由 Codex 独立验证。禁止把相邻任务“顺手一起做完”。

## 0. 状态约定

```text
TODO -> IMPLEMENTING -> READY_FOR_VERIFY -> PASS
                         └───────────────-> REWORK
TODO/IMPLEMENTING -> BLOCKED
```

只有 Codex 根据任务验收命令验证成功后才能进入 `PASS`。

---

# P0 — Repository Skeleton

目标：先建立可安装、可导入、可测试的最小 Python 工程。此阶段不写业务逻辑。

## T000 — Python package skeleton

- **Goal**：建立 `src` layout 和最小包元数据。
- **Depends**：无
- **Allowed files**：`pyproject.toml`, `src/agentipc/__init__.py`
- **Do**：定义项目名、版本、Python >=3.10、核心依赖与 dev optional dependencies；暴露 `__version__`。
- **Do not**：不创建 Agent/Runtime 实现。
- **Acceptance**：
  - `python -m pip install -e ".[dev]"`
  - `python -c "import agentipc; print(agentipc.__version__)"`

## T001 — Default configuration model

- **Goal**：建立统一配置对象，不读取业务环境变量。
- **Depends**：T000
- **Allowed files**：`src/agentipc/config.py`, `src/agentipc/resources/configs/default.yaml`, `tests/test_config.py`
- **Do**：Pydantic 配置模型；state/memory/artifact/results 根目录；provider 默认值；随机种子。
- **Do not**：不创建 provider。
- **Acceptance**：`pytest -q tests/test_config.py`

## T002 — Common ID and time helpers

- **Goal**：集中管理 message/task/trace ID 与 UTC 时间。
- **Depends**：T000
- **Allowed files**：`src/agentipc/utils.py`, `tests/test_utils.py`
- **Do**：纯函数；ID 带可读前缀；UTC timestamp。
- **Acceptance**：`pytest -q tests/test_utils.py`

## T003 — Minimal CLI entry point

- **Goal**：建立 `agentipc` CLI 入口，只提供 `version`。
- **Depends**：T000
- **Allowed files**：`src/agentipc/cli.py`, `pyproject.toml`, `tests/test_cli_version.py`
- **Do**：优先标准库 argparse。
- **Acceptance**：`agentipc version`

## T004 — Core smoke test

- **Goal**：建立最小 smoke test，验证包结构。
- **Depends**：T000-T003
- **Allowed files**：`tests/test_smoke.py`
- **Do**：只验证 import/config/CLI 入口基础可用。
- **Acceptance**：`pytest -q tests/test_smoke.py`

---

# P1 — Structured Protocol

目标：先完成纯数据契约，不连接 Runtime。

## T010 — Protocol enums

- **Goal**：实现协议版本和 `MessageType/ActionType/MessageStatus`。
- **Depends**：T000
- **Allowed files**：`src/agentipc/protocol/enums.py`, `src/agentipc/protocol/__init__.py`, `tests/protocol/test_enums.py`
- **Contract**：遵守 `docs/04_MODULE_CONTRACTS.md`。
- **Acceptance**：`pytest -q tests/protocol/test_enums.py`

## T011 — Reference DTOs

- **Goal**：实现 `StateRef/ArtifactRef/MemoryRef` Pydantic 模型。
- **Depends**：T010
- **Allowed files**：`src/agentipc/protocol/refs.py`, `tests/protocol/test_refs.py`
- **Do**：只做数据模型与基本 validation。
- **Do not**：不实现存储。
- **Acceptance**：`pytest -q tests/protocol/test_refs.py`

## T012 — AgentEnvelope schema

- **Goal**：实现统一消息模型。
- **Depends**：T010-T011, T002
- **Allowed files**：`src/agentipc/protocol/envelope.py`, `tests/protocol/test_envelope.py`
- **Do**：字段、默认值、ID factory、validation。
- **Acceptance**：`pytest -q tests/protocol/test_envelope.py`

## T013 — JSON protocol codec

- **Goal**：实现 Envelope JSON bytes round-trip。
- **Depends**：T012
- **Allowed files**：`src/agentipc/protocol/codec.py`, `tests/protocol/test_codec.py`
- **Do**：UTF-8；紧凑 JSON；decode 后类型完整恢复。
- **Acceptance**：`pytest -q tests/protocol/test_codec.py`

## T014 — Capability data model

- **Goal**：实现 `AgentCapability`。
- **Depends**：T010
- **Allowed files**：`src/agentipc/protocol/capability.py`, `tests/protocol/test_capability.py`
- **Acceptance**：`pytest -q tests/protocol/test_capability.py`

## T015 — Capability registry

- **Goal**：实现 register/get/discover/supports。
- **Depends**：T014
- **Allowed files**：`src/agentipc/protocol/registry.py`, `tests/protocol/test_registry.py`
- **Do**：内存实现即可；重复注册行为明确。
- **Acceptance**：`pytest -q tests/protocol/test_registry.py`

## T016 — Protocol control message builders

- **Goal**：提供 HELLO/REGISTER/DISCOVER/ACK builder。
- **Depends**：T012, T014
- **Allowed files**：`src/agentipc/protocol/builders.py`, `tests/protocol/test_builders.py`
- **Do**：builder 只构造合法 Envelope。
- **Acceptance**：`pytest -q tests/protocol/test_builders.py`

## T017 — TextAdapter minimal renderer

- **Goal**：把无引用 Envelope 渲染为稳定、可读自然语言文本。
- **Depends**：T012
- **Allowed files**：`src/agentipc/protocol/text_adapter.py`, `tests/protocol/test_text_adapter_basic.py`
- **Do**：先支持无 ref 情况；输出稳定便于测量。
- **Do not**：暂不 materialize state/artifact/memory。
- **Acceptance**：`pytest -q tests/protocol/test_text_adapter_basic.py`

## T018 — Protocol package regression

- **Goal**：补一个协议全链路 round-trip test。
- **Depends**：T010-T017
- **Allowed files**：`tests/protocol/test_protocol_integration.py`
- **Acceptance**：`pytest -q tests/protocol`

---

# P2 — Non-text State Exchange

目标：独立完成 NumPy -> Shared Memory -> StateRef -> NumPy 的真实闭环。

## T020 — Shared memory low-level writer

- **Goal**：创建 shared memory segment 并写入 ndarray bytes。
- **Depends**：T011
- **Allowed files**：`src/agentipc/state/shared_memory.py`, `tests/state/test_shm_write.py`
- **Do**：返回名称、shape、dtype、nbytes 等低层元数据。
- **Do not**：不创建 StateHub。
- **Acceptance**：`pytest -q tests/state/test_shm_write.py`

## T021 — Shared memory reader

- **Goal**：根据 metadata 打开 segment 并恢复 ndarray。
- **Depends**：T020
- **Allowed files**：`src/agentipc/state/shared_memory.py`, `tests/state/test_shm_read.py`
- **Acceptance**：数组值、shape、dtype 完全一致。

## T022 — Shared memory release/cleanup

- **Goal**：实现 close/unlink 和幂等清理。
- **Depends**：T021
- **Allowed files**：`src/agentipc/state/shared_memory.py`, `tests/state/test_shm_cleanup.py`
- **Acceptance**：重复 cleanup 不导致未处理异常；资源不可再次 resolve。

## T023 — In-process fallback backend

- **Goal**：实现网络/共享内存不可用时的 in-process ndarray store。
- **Depends**：T011
- **Allowed files**：`src/agentipc/state/inproc.py`, `tests/state/test_inproc.py`
- **Acceptance**：put/get/release。

## T024 — State checksum helper

- **Goal**：对 ndarray 内容生成稳定 checksum。
- **Depends**：T000
- **Allowed files**：`src/agentipc/state/checksum.py`, `tests/state/test_checksum.py`
- **Acceptance**：相同 bytes 相同 checksum；内容变化 checksum 变化。

## T025 — StateHub put_array

- **Goal**：实现 `StateHub.put_array()`，优先 shm，返回 `StateRef`。
- **Depends**：T020, T023, T024
- **Allowed files**：`src/agentipc/state/hub.py`, `tests/state/test_hub_put.py`
- **Acceptance**：ref 字段正确，transport 可识别。

## T026 — StateHub resolve_array

- **Goal**：实现 ref -> ndarray，并验证 checksum。
- **Depends**：T025, T021
- **Allowed files**：`src/agentipc/state/hub.py`, `tests/state/test_hub_resolve.py`
- **Acceptance**：round-trip 值一致；损坏/错误 ref 有明确异常。

## T027 — StateHub lifecycle API

- **Goal**：实现 exists/release/close/context manager。
- **Depends**：T026
- **Allowed files**：`src/agentipc/state/hub.py`, `tests/state/test_hub_lifecycle.py`
- **Acceptance**：`pytest -q tests/state/test_hub_lifecycle.py`

## T028 — Plan vector encoder

- **Goal**：把结构化 plan 编码为固定维度 `float32` compact vector。
- **Depends**：T000
- **Allowed files**：`src/agentipc/state/plan_vector.py`, `tests/state/test_plan_vector.py`
- **Do**：确定性；不需要 LLM；维度写入常量/配置。
- **Acceptance**：同 plan 同向量；不同关键字段至少有向量差异。

## T029 — State real-consumption integration test

- **Goal**：证明下游 resolve 后用向量参与计算，而不只是读 ref。
- **Depends**：T025-T028
- **Allowed files**：`tests/state/test_state_consumption.py`
- **Do**：构造两个候选，用 state vector 改变排序/得分。
- **Acceptance**：`pytest -q tests/state`

---

# P3 — Artifact Store

目标：长文本和结构化大结果内容寻址保存，消息只传 ArtifactRef。

## T030 — ArtifactStore filesystem layout

- **Goal**：创建 store root 与 digest 路径生成逻辑。
- **Depends**：T011, T001
- **Allowed files**：`src/agentipc/artifacts/store.py`, `tests/artifacts/test_layout.py`
- **Acceptance**：digest 路径确定性且不写 payload。

## T031 — Artifact put/get bytes

- **Goal**：完成 bytes 内容寻址存取。
- **Depends**：T030
- **Allowed files**：`src/agentipc/artifacts/store.py`, `tests/artifacts/test_bytes.py`
- **Acceptance**：同内容 digest 一致；get 原样返回。

## T032 — Artifact JSON helpers

- **Goal**：实现 `put_json/get_json`。
- **Depends**：T031
- **Allowed files**：`src/agentipc/artifacts/store.py`, `tests/artifacts/test_json.py`
- **Acceptance**：Unicode JSON round-trip。

## T033 — Artifact integrity validation

- **Goal**：读取时校验 sha256，损坏时明确失败。
- **Depends**：T031
- **Allowed files**：`src/agentipc/artifacts/store.py`, `tests/artifacts/test_integrity.py`
- **Acceptance**：篡改文件测试失败为预期异常。

## T034 — Artifact package regression

- **Goal**：覆盖 exists、重复写、空 payload、大于阈值 payload。
- **Depends**：T030-T033
- **Allowed files**：`tests/artifacts/test_artifact_integration.py`
- **Acceptance**：`pytest -q tests/artifacts`

---

# P4 — Providers

目标：先建立 mock-first provider，再提供可选真实 provider。

## T040 — Provider interfaces and response models

- **Goal**：实现 `LLMProvider`, `LLMResponse`, `EmbeddingProvider` 契约。
- **Depends**：T000
- **Allowed files**：`src/agentipc/providers/base.py`, `tests/providers/test_contracts.py`
- **Acceptance**：协议/抽象类型可被 fake 实现满足。

## T041 — MockLLMProvider

- **Goal**：提供完全离线、确定性 LLM mock。
- **Depends**：T040
- **Allowed files**：`src/agentipc/providers/mock_llm.py`, `tests/providers/test_mock_llm.py`
- **Do**：允许按输入关键词返回固定结构；记录调用次数。
- **Acceptance**：无网络运行测试。

## T042 — HashEmbeddingProvider

- **Goal**：实现确定性、固定维度、不依赖模型的 embedding。
- **Depends**：T040
- **Allowed files**：`src/agentipc/providers/hash_embedding.py`, `tests/providers/test_hash_embedding.py`
- **Do**：输出 `(n, dim)` float32；同文本确定性。
- **Acceptance**：`pytest -q tests/providers/test_hash_embedding.py`

## T043 — OpenAI-compatible LLM provider

- **Goal**：实现可选真实接口适配器。
- **Depends**：T040
- **Allowed files**：`src/agentipc/providers/openai_compatible.py`, `tests/providers/test_openai_provider_unit.py`, `pyproject.toml`
- **Do**：测试使用 monkeypatch/fake client，不调用公网。
- **Acceptance**：无 API Key 也能跑 unit test。

## T044 — Optional SentenceTransformer embedding provider

- **Goal**：实现懒加载的真实 embedding adapter。
- **Depends**：T040
- **Allowed files**：`src/agentipc/providers/sentence_transformer.py`, `tests/providers/test_sentence_transformer_unit.py`, `pyproject.toml`
- **Do**：import 缺失时给明确错误；单测不得下载模型。
- **Acceptance**：unit test 通过且不会联网。

## T045 — Provider factory

- **Goal**：根据配置创建 mock/openai 与 hash/sentence-transformer。
- **Depends**：T001, T041-T044
- **Allowed files**：`src/agentipc/providers/factory.py`, `tests/providers/test_factory.py`
- **Acceptance**：默认配置只构造 Mock + Hash。

## T046 — Provider package regression

- **Goal**：验证默认安装不需要 OpenAI/Transformers 即可运行核心 provider。
- **Depends**：T040-T045
- **Allowed files**：`tests/providers/test_provider_regression.py`
- **Acceptance**：`pytest -q tests/providers`

---

# P5 — Shared Memory Store

目标：完成 SQLite metadata + lightweight vector index + hybrid retrieval。

## T050 — MemoryRecord model

- **Goal**：实现 MemoryType/MemoryRecord。
- **Depends**：T011, T002
- **Allowed files**：`src/agentipc/memory/models.py`, `tests/memory/test_models.py`
- **Acceptance**：必填元数据 validation。

## T051 — SQLite schema initialization

- **Goal**：创建 memory 数据表和必要索引。
- **Depends**：T050, T001
- **Allowed files**：`src/agentipc/memory/sqlite_store.py`, `tests/memory/test_schema.py`
- **Do**：初始化可重复执行。
- **Acceptance**：临时 DB 创建成功并包含预期 schema。

## T052 — SQLite write/get

- **Goal**：实现记录写入与按 ID 获取。
- **Depends**：T051
- **Allowed files**：`src/agentipc/memory/sqlite_store.py`, `tests/memory/test_crud.py`
- **Acceptance**：MemoryRecord round-trip。

## T053 — SQLite update counters

- **Goal**：实现 reuse/success/failure/last_accessed 原子更新。
- **Depends**：T052
- **Allowed files**：`src/agentipc/memory/sqlite_store.py`, `tests/memory/test_counters.py`
- **Acceptance**：重复更新计数正确。

## T054 — In-memory vector index

- **Goal**：实现 memory_id -> float32 vector 的 add/search。
- **Depends**：T042
- **Allowed files**：`src/agentipc/memory/vector_index.py`, `tests/memory/test_vector_index.py`
- **Do**：NumPy cosine similarity；不引入 FAISS。
- **Acceptance**：已知向量 top-k 排序正确。

## T055 — Rebuild vector index from SQLite

- **Goal**：DB reopen 后从记录 embedding 重建 index。
- **Depends**：T052, T054
- **Allowed files**：`src/agentipc/memory/vector_index.py`, `src/agentipc/memory/sqlite_store.py`, `tests/memory/test_rebuild.py`
- **Acceptance**：关闭重开后语义索引仍可恢复。

## T056 — Keyword matcher

- **Goal**：独立实现 keyword overlap score。
- **Depends**：T050
- **Allowed files**：`src/agentipc/memory/scoring.py`, `tests/memory/test_keyword_score.py`
- **Acceptance**：大小写、重复 keyword、空 query 边界明确。

## T057 — Tag matcher

- **Goal**：独立实现 tag overlap score。
- **Depends**：T050
- **Allowed files**：`src/agentipc/memory/scoring.py`, `tests/memory/test_tag_score.py`
- **Acceptance**：`pytest -q tests/memory/test_tag_score.py`

## T058 — Semantic scorer

- **Goal**：调用 EmbeddingProvider + VectorIndex 得到 semantic score。
- **Depends**：T054, T042
- **Allowed files**：`src/agentipc/memory/scoring.py`, `tests/memory/test_semantic_score.py`
- **Acceptance**：测试只用 HashEmbedding。

## T059 — MemoryService write

- **Goal**：统一完成 embedding 生成 + SQLite write + vector add。
- **Depends**：T052, T054, T042
- **Allowed files**：`src/agentipc/memory/service.py`, `tests/memory/test_service_write.py`
- **Acceptance**：write 后 DB 和 index 都可见。

## T060 — MemoryService hybrid retrieve

- **Goal**：实现 0.60 semantic + 0.25 keyword + 0.15 tag。
- **Depends**：T056-T059
- **Allowed files**：`src/agentipc/memory/service.py`, `tests/memory/test_hybrid_retrieve.py`
- **Acceptance**：返回 `MemoryRef`，排序符合构造样例。

## T061 — MemoryService mark_used

- **Goal**：实现有效/无效复用反馈。
- **Depends**：T053, T059
- **Allowed files**：`src/agentipc/memory/service.py`, `tests/memory/test_mark_used.py`
- **Acceptance**：reuse/success/failure 计数准确。

## T062 — Memory persistence integration

- **Goal**：Task A write -> close -> reopen -> Task B retrieve。
- **Depends**：T055, T060
- **Allowed files**：`tests/memory/test_persistence_integration.py`
- **Acceptance**：`pytest -q tests/memory`

---

# P6 — Metrics and Trace Foundations

目标：Runtime 集成前先有统一观测接口。

## T070 — MetricsSnapshot model

- **Goal**：实现固定指标字段模型。
- **Depends**：T000
- **Allowed files**：`src/agentipc/evaluation/metrics.py`, `tests/evaluation/test_metrics_model.py`
- **Contract**：字段名严格遵守 MODULE_CONTRACTS。
- **Acceptance**：模型默认值和 JSON 序列化测试。

## T071 — MetricsCollector counters

- **Goal**：实现消息、字符、协议 bytes、state、artifact、memory、tool counters。
- **Depends**：T070
- **Allowed files**：`src/agentipc/evaluation/metrics.py`, `tests/evaluation/test_metrics_collector.py`
- **Acceptance**：逐项增量可预测。

## T072 — Task timer

- **Goal**：实现 start/stop 与 latency_ms。
- **Depends**：T071
- **Allowed files**：`src/agentipc/evaluation/metrics.py`, `tests/evaluation/test_timer.py`
- **Acceptance**：幂等与异常路径明确。

## T073 — Text counter

- **Goal**：实现 exact char count 与可选 token count。
- **Depends**：T000
- **Allowed files**：`src/agentipc/evaluation/text_counter.py`, `tests/evaluation/test_text_counter.py`, `pyproject.toml`
- **Do**：char count 永远可用；tiktoken 可选；必须标记 token_method。
- **Acceptance**：未安装 tiktoken 时不影响 char 测试。

## T074 — JSONL trace logger

- **Goal**：逐事件写 JSONL，包含 trace/task/message/ref 信息。
- **Depends**：T012
- **Allowed files**：`src/agentipc/evaluation/trace.py`, `tests/evaluation/test_trace.py`
- **Acceptance**：多事件按行写入，可重新解析。

## T075 — Metrics/trace regression

- **Goal**：验证一次 fake 消息发送同时产生 metrics 与 trace。
- **Depends**：T071-T074
- **Allowed files**：`tests/evaluation/test_observability_integration.py`
- **Acceptance**：`pytest -q tests/evaluation/test_observability_integration.py`

---

# P7 — Agents

目标：四个 Agent 独立可测试，不先依赖完整 Orchestrator。

## T080 — BaseAgent contract

- **Goal**：实现 BaseAgent ABC 与 capability 属性。
- **Depends**：T012
- **Allowed files**：`src/agentipc/agents/base.py`, `tests/agents/test_base.py`
- **Acceptance**：无法实例化缺少 handle 的子类。

## T081 — Planner deterministic core

- **Goal**：Planner 把任务转换为结构化 plan。
- **Depends**：T080, T041
- **Allowed files**：`src/agentipc/agents/planner.py`, `tests/agents/test_planner.py`
- **Do**：先支持 Mock provider；输出字段稳定。
- **Do not**：暂不写 StateHub。
- **Acceptance**：PLAN RESULT Envelope 合法。

## T082 — Retriever local knowledge search

- **Goal**：基于本地小知识集合做关键词/简单相似检索。
- **Depends**：T080, T042
- **Allowed files**：`src/agentipc/agents/retriever.py`, `tests/agents/test_retriever_basic.py`
- **Do**：先接受 inline plan args。
- **Do not**：暂不消费 StateRef。
- **Acceptance**：固定语料命中预期文档。

## T083 — Retriever StateRef consumption

- **Goal**：Retriever resolve Planner state vector，并让向量参与候选 ranking。
- **Depends**：T082, T025-T029
- **Allowed files**：`src/agentipc/agents/retriever.py`, `tests/agents/test_retriever_state.py`
- **Acceptance**：不同 state vector 可改变构造样例 ranking；不是只记录 ref。

## T084 — Executor deterministic operation core

- **Goal**：Executor 接受结构化输入并执行少量安全内置操作。
- **Depends**：T080
- **Allowed files**：`src/agentipc/agents/executor.py`, `tests/agents/test_executor_basic.py`
- **Do**：例如 arithmetic/json transform；CodeAct 后续单独实现。
- **Acceptance**：EXECUTE RESULT Envelope 合法。

## T085 — Summarizer deterministic core

- **Goal**：Summarizer 将上游结果整理为最终 answer 与 memory candidate 数据。
- **Depends**：T080, T041
- **Allowed files**：`src/agentipc/agents/summarizer.py`, `tests/agents/test_summarizer.py`
- **Do not**：暂不直接写 MemoryService。
- **Acceptance**：输出结构可供 Runtime 写 memory。

## T086 — Agent capability declarations

- **Goal**：四 Agent 提供固定 capability 列表。
- **Depends**：T081-T085
- **Allowed files**：四个 Agent 文件的 capability 部分, `tests/agents/test_capabilities.py`
- **Acceptance**：plan/retrieve/execute/summarize 均可被 discover。

## T087 — Agent package regression

- **Goal**：四 Agent 用 mock context 独立执行。
- **Depends**：T081-T086
- **Allowed files**：`tests/agents/test_agents_regression.py`
- **Acceptance**：`pytest -q tests/agents`

---

# P8 — Runtime Integration

目标：小步把协议、Agent、refs、Memory 串起来。每次只接一种基础设施。

## T090 — RunContext model

- **Goal**：实现共享运行上下文容器。
- **Depends**：P1-P7 已有基础类型
- **Allowed files**：`src/agentipc/runtime/context.py`, `tests/runtime/test_context.py`
- **Do**：只持有依赖；不执行业务。
- **Acceptance**：可用 mock components 构造。

## T091 — Runtime agent registry

- **Goal**：按 agent_id 注册/获取 BaseAgent。
- **Depends**：T080, T090
- **Allowed files**：`src/agentipc/runtime/agent_registry.py`, `tests/runtime/test_agent_registry.py`
- **Acceptance**：duplicate/unknown 行为明确。

## T092 — Router direct dispatch

- **Goal**：Envelope receiver -> 对应 Agent.handle。
- **Depends**：T091, T012
- **Allowed files**：`src/agentipc/runtime/router.py`, `tests/runtime/test_router_dispatch.py`
- **Do**：只实现 direct in-process dispatch。
- **Acceptance**：fake agent 收到请求并返回结果。

## T093 — Runtime capability bootstrap

- **Goal**：启动时把 Agent capability 注册到 Protocol Registry。
- **Depends**：T015, T086, T091
- **Allowed files**：`src/agentipc/runtime/bootstrap.py`, `tests/runtime/test_capability_bootstrap.py`
- **Acceptance**：四 Agent 均可通过 capability discover。

## T094 — Handshake flow

- **Goal**：Runtime 启动时执行 HELLO/REGISTER/ACK 事件并写 trace。
- **Depends**：T016, T074, T093
- **Allowed files**：`src/agentipc/runtime/bootstrap.py`, `tests/runtime/test_handshake.py`
- **Acceptance**：trace 中存在控制消息且协议版本一致。

## T095 — Orchestrator minimal structured chain

- **Goal**：串联 Planner->Retriever->Executor->Summarizer，不接 state/memory/artifact。
- **Depends**：T090-T094, T087
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_orchestrator_structured_min.py`
- **Acceptance**：单任务成功、4 个业务阶段按序出现。

## T096 — Structured transport metrics

- **Goal**：Orchestrator 每个 Envelope 记录 message/protocol bytes。
- **Depends**：T095, T071, T013
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_structured_metrics.py`
- **Acceptance**：message_count 和 protocol_bytes 非零且可预测。

## T097 — Text transport path

- **Goal**：同一内部 Envelope 经 TextAdapter 渲染再传给接收方适配层。
- **Depends**：T095, T017, T073
- **Allowed files**：`src/agentipc/runtime/text_transport.py`, `src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_text_mode.py`
- **Acceptance**：最终业务结果与 structured 构造样例一致；text_chars > 0。

## T098 — Reference resolver interface

- **Goal**：统一 materialize Artifact/State/Memory 引用给 TextAdapter。
- **Depends**：T026, T032, T060
- **Allowed files**：`src/agentipc/runtime/reference_resolver.py`, `tests/runtime/test_reference_resolver.py`
- **Acceptance**：三个 ref 类型均能 resolve。

## T099 — TextAdapter reference materialization

- **Goal**：text mode 展开 refs，使 baseline 携带语义等价内容。
- **Depends**：T098, T017
- **Allowed files**：`src/agentipc/protocol/text_adapter.py`, `tests/protocol/test_text_adapter_refs.py`
- **Acceptance**：ref 内容确实出现在 text baseline；引用本身不是唯一信息。

## T100 — Artifact integration in Runtime

- **Goal**：Retriever 较大 evidence 写 ArtifactStore，向 Executor 传 ArtifactRef。
- **Depends**：T095, P3
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_artifact_flow.py`
- **Acceptance**：structured trace 只含 ref/summary；下游 resolve 后结果正确。

## T101 — State integration in Runtime

- **Goal**：Planner plan -> vector -> StateHub -> Retriever consumption。
- **Depends**：T095, T083, P2
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_state_flow.py`
- **Acceptance**：state_transfer_count=预期值；Retriever 使用 state。

## T102 — Memory read integration

- **Goal**：任务开始/检索阶段查询历史 memory，并把 MemoryRef 提供给 Agent。
- **Depends**：T095, T060
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_memory_read_flow.py`
- **Acceptance**：第二任务可看到第一任务 memory hit。

## T103 — Memory write integration

- **Goal**：Summarizer memory candidate -> MemoryService.write。
- **Depends**：T085, T059, T095
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_memory_write_flow.py`
- **Acceptance**：任务完成后 DB 新增记录。

## T104 — Memory effective-use feedback

- **Goal**：当 memory 被实际用于避免重复工作/得到正确结果时 mark_used。
- **Depends**：T102-T103, T061
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_memory_feedback_flow.py`
- **Acceptance**：retrieved/used/effective 三个指标语义区分。

## T105 — RunResult DTO

- **Goal**：统一 Runtime 返回结果。
- **Depends**：T095, T070
- **Allowed files**：`src/agentipc/runtime/result.py`, `tests/runtime/test_run_result.py`
- **Acceptance**：JSON serialize；error 可选。

## T106 — Runtime resource cleanup

- **Goal**：任务完成/失败后释放 per-task shared memory 等资源。
- **Depends**：T101, T027
- **Allowed files**：`src/agentipc/runtime/orchestrator.py`, `tests/runtime/test_cleanup.py`
- **Acceptance**：成功和异常路径均 cleanup。

## T107 — Runtime regression

- **Goal**：text 与 structured 各跑一个完整 mock 任务。
- **Depends**：T095-T106
- **Allowed files**：`tests/runtime/test_runtime_regression.py`
- **Acceptance**：`pytest -q tests/runtime`

---

# P9 — Restricted CodeAct Sandbox

目标：提供比赛演示级受限 Python 执行，不宣称为强安全沙箱。

## T110 — SandboxResult model

- **Goal**：实现统一执行结果 DTO。
- **Depends**：T000
- **Allowed files**：`src/agentipc/sandbox/models.py`, `tests/sandbox/test_models.py`
- **Acceptance**：contract 字段完整。

## T111 — Temporary workspace runner

- **Goal**：每次执行创建独立临时目录，运行 Python 子进程。
- **Depends**：T110
- **Allowed files**：`src/agentipc/sandbox/python_runner.py`, `tests/sandbox/test_basic_run.py`
- **Acceptance**：stdout/exit_code 正确。

## T112 — Timeout handling

- **Goal**：超时后终止子进程并返回 `timed_out=True`。
- **Depends**：T111
- **Allowed files**：`src/agentipc/sandbox/python_runner.py`, `tests/sandbox/test_timeout.py`
- **Acceptance**：无限循环在测试超时内被终止。

## T113 — Output size limit

- **Goal**：限制 stdout/stderr 捕获长度，避免内存失控。
- **Depends**：T111
- **Allowed files**：`src/agentipc/sandbox/python_runner.py`, `tests/sandbox/test_output_limit.py`
- **Acceptance**：超长输出被截断并标记。

## T114 — Resource limit helper on Linux

- **Goal**：best-effort 设置 CPU/地址空间等 rlimit。
- **Depends**：T111
- **Allowed files**：`src/agentipc/sandbox/limits.py`, `tests/sandbox/test_limits.py`
- **Do**：Windows/不支持平台可显式 skip/fallback。
- **Acceptance**：接口行为确定，不要求 CI 强制耗尽内存。

## T115 — Restricted environment variables and cwd

- **Goal**：子进程使用精简 env 与独立 cwd。
- **Depends**：T111
- **Allowed files**：`src/agentipc/sandbox/python_runner.py`, `tests/sandbox/test_environment.py`
- **Acceptance**：不继承测试注入的敏感环境变量。

## T116 — Executor CodeAct hook

- **Goal**：Executor 对明确 code action 调用 PythonSandbox。
- **Depends**：T084, T111-T115
- **Allowed files**：`src/agentipc/agents/executor.py`, `tests/agents/test_executor_codeact.py`
- **Acceptance**：tool_call_count 可被 Runtime 记录；错误结构化返回。

## T117 — Sandbox regression

- **Goal**：正常、异常、timeout 三条路径。
- **Depends**：T110-T116
- **Allowed files**：`tests/sandbox/test_sandbox_regression.py`
- **Acceptance**：`pytest -q tests/sandbox tests/agents/test_executor_codeact.py`

---

# P10 — Benchmark Framework

目标：从单次 Runtime 结果构建可复现的 A/B/C/D 实验。

## T120 — ExperimentConfig model

- **Goal**：定义 A/B/C/D feature flags。
- **Depends**：T001
- **Allowed files**：`src/agentipc/evaluation/experiment.py`, `tests/evaluation/test_experiment_config.py`
- **Acceptance**：A/B/C/D 固定配置与文档一致。

## T121 — Single-run benchmark adapter

- **Goal**：给定 ExperimentConfig + Task 调一次 Runtime。
- **Depends**：T107, T120
- **Allowed files**：`src/agentipc/evaluation/runner.py`, `tests/evaluation/test_single_run.py`
- **Acceptance**：返回标准 raw record。

## T122 — Repeated-run loop

- **Goal**：按 seed 列表重复单一实验配置。
- **Depends**：T121
- **Allowed files**：`src/agentipc/evaluation/runner.py`, `tests/evaluation/test_repeat.py`
- **Acceptance**：run 数量与 seed 记录准确。

## T123 — A/B/C/D suite runner

- **Goal**：同任务集依次执行四配置。
- **Depends**：T122
- **Allowed files**：`src/agentipc/evaluation/runner.py`, `tests/evaluation/test_abcd_suite.py`
- **Acceptance**：四配置任务输入 hash 相同。

## T124 — Raw JSONL writer

- **Goal**：保存每次 task/run 原始指标。
- **Depends**：T121
- **Allowed files**：`src/agentipc/evaluation/io.py`, `tests/evaluation/test_raw_writer.py`
- **Acceptance**：append/parse；Unicode 安全。

## T125 — Environment snapshot

- **Goal**：保存 OS/Python/platform/依赖模式/token method。
- **Depends**：T000
- **Allowed files**：`src/agentipc/evaluation/env.py`, `tests/evaluation/test_env_snapshot.py`
- **Acceptance**：JSON serializable。

## T126 — Results directory creation

- **Goal**：按 timestamp + suite 创建不可默认覆盖的结果目录。
- **Depends**：T124-T125, T001
- **Allowed files**：`src/agentipc/evaluation/io.py`, `tests/evaluation/test_result_dir.py`
- **Acceptance**：同名冲突时创建新目录或明确失败，不覆盖。

## T127 — Aggregate statistics

- **Goal**：实现 mean/std/min/max；后续可扩 P50/P95。
- **Depends**：T070
- **Allowed files**：`src/agentipc/evaluation/stats.py`, `tests/evaluation/test_stats.py`
- **Acceptance**：固定样例数值正确。

## T128 — Derived metrics

- **Goal**：计算 token/char saving、latency improvement、repeat work reduction、effective hit rate。
- **Depends**：T127
- **Allowed files**：`src/agentipc/evaluation/derived.py`, `tests/evaluation/test_derived.py`
- **Acceptance**：零分母边界有定义。

## T129 — Summary JSON writer

- **Goal**：从 raw 结果聚合为 summary.json。
- **Depends**：T127-T128
- **Allowed files**：`src/agentipc/evaluation/io.py`, `tests/evaluation/test_summary_writer.py`
- **Acceptance**：包含每配置 summary + derived。

## T130 — Markdown report renderer

- **Goal**：从 summary 生成可提交的基础 report.md。
- **Depends**：T129
- **Allowed files**：`src/agentipc/evaluation/report.py`, `tests/evaluation/test_report.py`
- **Acceptance**：必须含通信、状态、记忆、时延四部分表格。

## T131 — Benchmark reproducibility regression

- **Goal**：Mock provider + 固定 seed 连跑两次，结构与确定性字段一致。
- **Depends**：T123-T130
- **Allowed files**：`tests/evaluation/test_reproducibility.py`
- **Acceptance**：`pytest -q tests/evaluation`

---

# P11 — Continuous Scenario A: Knowledge Chain

目标：构建原创、本地、无下载依赖的 10 轮连续知识任务。

## T140 — Knowledge document fixture format

- **Goal**：定义本地知识文档结构和 loader。
- **Depends**：T082
- **Allowed files**：`tests/scenarios/knowledge_chain/knowledge/*.md`, `src/agentipc/scenarios/knowledge_loader.py`, `tests/scenarios/test_knowledge_loader.py`
- **Do**：先只放少量测试文档。
- **Acceptance**：loader 可读取文档 ID/title/body/tags。

## T141 — Knowledge task schema

- **Goal**：定义连续任务 JSON schema/loader。
- **Depends**：T000
- **Allowed files**：`src/agentipc/scenarios/models.py`, `tests/scenarios/test_task_schema.py`
- **Acceptance**：group_id/round/query/expected/reuse_hint 可解析。

## T142 — Knowledge Chain rounds 1-5

- **Goal**：编写前 5 轮原创任务与 expected evidence。
- **Depends**：T140-T141
- **Allowed files**：`tests/scenarios/knowledge_chain/tasks.json`
- **Do**：形成明确连续关系；后续问题复用前轮信息。
- **Acceptance**：schema loader 成功；无代码修改。

## T143 — Knowledge Chain rounds 6-10

- **Goal**：补齐 10 轮并增强跨任务复用点。
- **Depends**：T142
- **Allowed files**：`tests/scenarios/knowledge_chain/tasks.json`
- **Acceptance**：正好/至少 10 轮；存在可验证重复检索点。

## T144 — Knowledge task evaluator

- **Goal**：实现 deterministic success 判定。
- **Depends**：T141-T143
- **Allowed files**：`src/agentipc/scenarios/knowledge_eval.py`, `tests/scenarios/test_knowledge_eval.py`
- **Acceptance**：正确/错误 answer 样例可区分。

## T145 — Knowledge Chain runner adapter

- **Goal**：把 task loader 转成 Runtime 输入，按顺序保持同一 Memory DB。
- **Depends**：T107, T143-T144
- **Allowed files**：`src/agentipc/scenarios/knowledge_chain.py`, `tests/scenarios/test_knowledge_chain_smoke.py`
- **Acceptance**：Mock 下至少跑 3 轮 smoke。

## T146 — Knowledge 10-round stability test

- **Goal**：完整运行 10 轮 Full System。
- **Depends**：T145
- **Allowed files**：`tests/scenarios/test_knowledge_chain_10round.py`
- **Acceptance**：10 轮不崩溃；存在 memory_retrieved > 0。

---

# P12 — Continuous Scenario B: CodeAct Chain

目标：构建原创、本地、无下载依赖的 10 轮代码/数据处理连续任务。

## T150 — CodeAct task schema extension

- **Goal**：为任务模型增加 input artifact / expected structured result 等字段。
- **Depends**：T141
- **Allowed files**：`src/agentipc/scenarios/models.py`, `tests/scenarios/test_codeact_schema.py`
- **Acceptance**：不破坏 Knowledge task parsing。

## T151 — CodeAct fixture data

- **Goal**：准备小型 CSV/JSON/log/config 输入文件。
- **Depends**：无
- **Allowed files**：`tests/scenarios/codeact_chain/data/*`
- **Do**：原创小数据，无外部下载。
- **Acceptance**：文件 UTF-8，体积小，可进 Git。

## T152 — CodeAct rounds 1-5

- **Goal**：设计前 5 轮，覆盖解析/过滤/聚合/配置计算。
- **Depends**：T150-T151
- **Allowed files**：`tests/scenarios/codeact_chain/tasks.json`
- **Acceptance**：loader 成功，expected result 明确。

## T153 — CodeAct rounds 6-10

- **Goal**：补齐 10 轮，加入可复用策略/中间结果。
- **Depends**：T152
- **Allowed files**：`tests/scenarios/codeact_chain/tasks.json`
- **Acceptance**：至少两个任务可通过 Memory 减少重复计算。

## T154 — CodeAct evaluator

- **Goal**：对 scalar/list/dict structured output 做 deterministic compare。
- **Depends**：T150-T153
- **Allowed files**：`src/agentipc/scenarios/codeact_eval.py`, `tests/scenarios/test_codeact_eval.py`
- **Acceptance**：常见类型与浮点容差明确。

## T155 — CodeAct Chain runner adapter

- **Goal**：按 10 轮顺序运行 Runtime + Sandbox。
- **Depends**：T116, T153-T154
- **Allowed files**：`src/agentipc/scenarios/codeact_chain.py`, `tests/scenarios/test_codeact_chain_smoke.py`
- **Acceptance**：Mock 下至少跑 3 轮 smoke。

## T156 — CodeAct 10-round stability test

- **Goal**：完整运行 10 轮 Full System。
- **Depends**：T155
- **Allowed files**：`tests/scenarios/test_codeact_chain_10round.py`
- **Acceptance**：10 轮完成；tool_call_count > 0；无残留临时子进程。

## T157 — Combined 20-round smoke

- **Goal**：Knowledge 10 + CodeAct 10 连续执行。
- **Depends**：T146, T156
- **Allowed files**：`tests/scenarios/test_combined_20round.py`
- **Acceptance**：`pytest -q tests/scenarios/test_combined_20round.py`

---

# P13 — CLI Productization

## T160 — `agentipc doctor`

- **Goal**：检查 Python、目录权限、SQLite、shared_memory、可选 provider 状态。
- **Depends**：核心基础模块
- **Allowed files**：`src/agentipc/cli.py`, `src/agentipc/doctor.py`, `tests/test_cli_doctor.py`
- **Acceptance**：无网络环境能输出 machine-readable/人类可读结果至少一种。

## T161 — `agentipc demo`

- **Goal**：运行一个短的 text vs structured/full demo。
- **Depends**：T107, T145
- **Allowed files**：`src/agentipc/cli.py`, `src/agentipc/demo.py`, `tests/test_cli_demo.py`
- **Acceptance**：`agentipc demo --provider mock` 返回 0。

## T162 — `agentipc benchmark`

- **Goal**：暴露 suite/repeat/seed/provider 参数。
- **Depends**：T123-T130
- **Allowed files**：`src/agentipc/cli.py`, `tests/test_cli_benchmark.py`
- **Acceptance**：smoke suite 写完整结果目录。

## T163 — `agentipc run-scenario`

- **Goal**：单独执行 knowledge/codeact 场景并输出结果目录。
- **Depends**：T145, T155
- **Allowed files**：`src/agentipc/cli.py`, `tests/test_cli_scenario.py`
- **Acceptance**：两个 scenario name 均可解析。

## T164 — CLI regression

- **Goal**：version/doctor/demo/benchmark/run-scenario 全部 smoke。
- **Depends**：T160-T163
- **Allowed files**：`tests/test_cli_regression.py`
- **Acceptance**：CLI smoke 全部返回 0。

---

# P14 — Minimal Dashboard

目标：优先结果展示，不做复杂前端工程。

## T170 — Result repository reader

- **Goal**：扫描 `results/` 并读取 summary/env/report metadata。
- **Depends**：T126-T130
- **Allowed files**：`src/agentipc/dashboard/results.py`, `tests/dashboard/test_results_reader.py`
- **Acceptance**：忽略损坏/不完整目录并给出状态。

## T171 — Dashboard app skeleton

- **Goal**：创建最小 FastAPI/静态服务入口。
- **Depends**：T170
- **Allowed files**：`src/agentipc/dashboard/app.py`, `pyproject.toml`, `tests/dashboard/test_app_smoke.py`
- **Do**：FastAPI 为 optional `dashboard` dependency。
- **Acceptance**：TestClient 根路径 200。

## T172 — `/api/runs`

- **Goal**：返回运行列表。
- **Depends**：T171
- **Allowed files**：`src/agentipc/dashboard/app.py`, `tests/dashboard/test_runs_api.py`
- **Acceptance**：fixture results 能列出 run id/config。

## T173 — `/api/runs/{id}`

- **Goal**：返回某次 summary + derived + env。
- **Depends**：T172
- **Allowed files**：`src/agentipc/dashboard/app.py`, `tests/dashboard/test_run_detail_api.py`
- **Acceptance**：不存在 run 返回 404。

## T174 — Trace API

- **Goal**：按 run/task 返回 trace events。
- **Depends**：T173, T074
- **Allowed files**：`src/agentipc/dashboard/app.py`, `tests/dashboard/test_trace_api.py`
- **Acceptance**：事件保持顺序。

## T175 — Static HTML shell

- **Goal**：单页 HTML + 原生 CSS/JS，显示 run 选择和基础信息。
- **Depends**：T171
- **Allowed files**：`src/agentipc/dashboard/static/index.html`, `src/agentipc/dashboard/static/app.js`, `src/agentipc/dashboard/static/styles.css`
- **Acceptance**：不要求 Node/npm。

## T176 — A/B/C/D comparison view

- **Goal**：展示消息、字符/token、时延、state、memory 指标对比。
- **Depends**：T173, T175
- **Allowed files**：`src/agentipc/dashboard/static/app.js`, `src/agentipc/dashboard/static/index.html`, `src/agentipc/dashboard/static/styles.css`
- **Acceptance**：对 fixture summary 正确显示四配置。

## T177 — Agent timeline view

- **Goal**：可视化 Planner->Retriever->Executor->Summarizer 事件。
- **Depends**：T174-T175
- **Allowed files**：`src/agentipc/dashboard/static/app.js`, `src/agentipc/dashboard/static/index.html`, `src/agentipc/dashboard/static/styles.css`
- **Acceptance**：按 trace 顺序展示 sender/action/receiver。

## T178 — State and Memory view

- **Goal**：显示 StateRef transport/bytes 与 Memory hits/used/effective。
- **Depends**：T174-T175
- **Allowed files**：`src/agentipc/dashboard/static/app.js`, `src/agentipc/dashboard/static/index.html`, `src/agentipc/dashboard/static/styles.css`
- **Acceptance**：无数据时有空状态，不报 JS 错。

## T179 — `agentipc dashboard`

- **Goal**：CLI 启动 Dashboard。
- **Depends**：T171-T178
- **Allowed files**：`src/agentipc/cli.py`, `tests/dashboard/test_cli_dashboard.py`
- **Acceptance**：启动参数 host/port/results-dir 可解析。

## T180 — Dashboard regression

- **Goal**：API + static fixture smoke。
- **Depends**：T170-T179
- **Allowed files**：`tests/dashboard/test_dashboard_regression.py`
- **Acceptance**：`pytest -q tests/dashboard`

---

# P15 — openEuler and Packaging

## T190 — `.env.example`

- **Goal**：只提供非敏感变量名和注释。
- **Depends**：T043
- **Allowed files**：`.env.example`
- **Acceptance**：不得包含真实 key/token。

## T191 — Linux install script

- **Goal**：创建 venv、安装 core/dev 依赖。
- **Depends**：T000
- **Allowed files**：`demo/scripts/install.sh`
- **Do**：不自动下载模型。
- **Acceptance**：shellcheck 可选；至少在通用 Linux dry review 无明显 Bash 错误。

## T192 — openEuler environment check script

- **Goal**：检查 `/etc/os-release`、Python、shared memory、SQLite。
- **Depends**：T160
- **Allowed files**：`demo/scripts/check_openeuler.sh`
- **Acceptance**：非 openEuler 也能输出明确提示而非异常退出堆栈。

## T193 — Test wrapper script

- **Goal**：统一执行核心测试并记录日志。
- **Depends**：测试体系完成
- **Allowed files**：`tests/scripts/run_tests.sh`
- **Acceptance**：错误码透传。

## T194 — Benchmark wrapper script

- **Goal**：运行正式 A/B/C/D benchmark 并打印结果路径。
- **Depends**：T162
- **Allowed files**：`tests/scripts/run_benchmark.sh`
- **Acceptance**：provider/seed/repeat 可环境变量覆盖。

## T195 — openEuler verify script

- **Goal**：串联 check/install 已完成环境后的 doctor/test/demo/smoke benchmark。
- **Depends**：T191-T194, T164
- **Allowed files**：`demo/scripts/verify_openeuler.sh`
- **Acceptance**：任一步失败返回非零；日志说明失败阶段。

## T196 — Wheel build smoke

- **Goal**：验证 wheel build/install/import/CLI。
- **Depends**：T164
- **Allowed files**：`tests/packaging/test_package_metadata.py`, `demo/scripts/package_smoke.sh`
- **Acceptance**：在新 venv 安装 wheel 后 `agentipc version` 成功。

---

# P16 — Final Documentation and Evidence

这些任务应在对应实现稳定后再执行，避免文档提前“写未来事实”。

## T200 — README final quickstart

- **Goal**：把 README 更新成真实可执行命令。
- **Depends**：T164, T195
- **Allowed files**：`README.md`
- **Acceptance**：README 命令由 Codex 实际验证。

## T201 — Protocol specification

- **Goal**：根据最终代码写 `docs/PROTOCOL_SPEC.md`。
- **Depends**：P1, P8 完成
- **Allowed files**：`docs/PROTOCOL_SPEC.md`
- **Acceptance**：字段与代码一致，无不存在能力。

## T202 — State exchange document

- **Goal**：写生成、传递、接收、消费、cleanup、fallback。
- **Depends**：P2, T101, T106
- **Allowed files**：`docs/STATE_EXCHANGE.md`
- **Acceptance**：包含一条真实 trace 示例（来自结果，非手工伪造）。

## T203 — Shared memory document

- **Goal**：写 schema、SQLite、检索、反馈、跨任务复用。
- **Depends**：P5, T102-T104
- **Allowed files**：`docs/SHARED_MEMORY.md`
- **Acceptance**：字段与实现一致。

## T204 — Deployment document

- **Goal**：写 openEuler/Linux 安装、配置、运行、排错。
- **Depends**：P15
- **Allowed files**：`docs/DEPLOYMENT.md`
- **Acceptance**：Codex 按文档从干净环境复现核心命令。

## T205 — Test report

- **Goal**：汇总 unit/integration/stability/openEuler 测试。
- **Depends**：测试基本稳定
- **Allowed files**：`docs/TEST_REPORT.md`
- **Acceptance**：所有数字有日志/报告来源。

## T206 — Experiment report

- **Goal**：使用真实 A/B/C/D 结果编写实验报告。
- **Depends**：正式 benchmark 完成
- **Allowed files**：`docs/EXPERIMENT_REPORT.md`
- **Acceptance**：所有性能数字可回链 `results/`；不得先写结论后补数字。

## T207 — Limitations

- **Goal**：如实记录 mock/hash embedding、sandbox 安全边界、单机 shared memory 等限制。
- **Depends**：核心实现完成
- **Allowed files**：`docs/LIMITATIONS.md`
- **Acceptance**：不把未来计划写成已完成功能。

## T208 — Demonstration script

- **Goal**：生成 4-6 分钟演示视频脚本。
- **Depends**：Dashboard、正式结果、openEuler 验证
- **Allowed files**：`docs/VIDEO_SCRIPT.md`
- **Acceptance**：每个演示步骤有实际命令/页面。

## T209 — Final requirement audit

- **Goal**：逐项核对 `02_REQUIREMENTS_TRACEABILITY.md`。
- **Depends**：T200-T208
- **Allowed files**：`docs/02_REQUIREMENTS_TRACEABILITY.md`, `docs/10_DELIVERABLE_CHECKLIST.md`, `docs/08_PROJECT_STATUS.md`
- **Acceptance**：任何没有证据的 Requirement 不得标完成。

---

# 关键里程碑门禁

## Gate M0 — 可安装骨架

必须 PASS：T000-T004。

之后才允许开始大规模模块开发。

## Gate M1 — 协议闭环

必须 PASS：T010-T018。

证据：Envelope 可构造、编码、解码、文本映射、能力注册发现。

## Gate M2 — 三个基础设施独立闭环

必须 PASS：
- State T020-T029
- Artifact T030-T034
- Providers T040-T046
- Memory T050-T062

此时尚不要求 Runtime 集成。

## Gate M3 — 最小系统闭环

必须 PASS：T070-T107。

证据：text/structured 两模式都可完成单任务。

**到 M3 为止，已经有一个可演示最小系统。**

## Gate M4 — CodeAct + Benchmark

必须 PASS：T110-T131。

证据：A/B/C/D 可运行并生成可追溯结果。

## Gate M5 — 比赛连续任务闭环

必须 PASS：T140-T157。

证据：两组各 10 轮。

**到 M5 为止，达到“最低可提交功能成品”标准。**

## Gate M6 — 产品化与 openEuler

必须 PASS：T160-T196。

Dashboard 若出现时间风险，优先保证 CLI + result report + openEuler；但最终提交前应尽量完成最小 Dashboard。

## Gate M7 — 最终交付

必须 PASS：T200-T209。

---

# 时间不足时的砍功能顺序

如果截止时间逼近，按下面顺序砍，不能反过来：

1. 先砍 SentenceTransformerProvider（保留 HashEmbedding）。
2. 再砍真实 OpenAI 实验规模（保留 adapter + 小规模真实演示）。
3. 再砍 Dashboard 高级 trace 视觉效果。
4. 再砍 Token 精确计数，只保留 exact chars + provider token（若有）。
5. 再砍 Sandbox 更强资源隔离，只保留 timeout/temp dir/输出限制并明确限制。

**绝不能砍：**

- 4 Agent
- text/structured 双模式
- 结构化协议
- capability register/discover
- 非文本 StateRef 且真实消费
- Shared Memory 或明确的 Linux shared-memory 主路径
- 共享记忆跨任务复用
- 两组连续任务
- A/B/C/D 对比
- 核心指标
- 10 轮稳定
- openEuler 验证
- 完整交付文档
