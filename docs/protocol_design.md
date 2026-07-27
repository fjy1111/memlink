# MemLink 通信协议设计

## 1. 设计目标

协议需要可验证、可追踪、可统计，同时保留纯文本基线。structured 模式不承诺在所有指标上更快，而是提供明确的动作、能力、证据、引用和状态边界。

## 2. text 模式基线

text 模式使用 `TextMessage`，字段为 message ID、task ID、sender、receiver、完整 content 和时间戳。四个 Agent 传递完整文本，不进行 MessagePack 序列化。

## 3. structured 模式

structured 模式使用协议版本 `1.0` 的 `AgentMessage`。所有消息进入 `ProtocolTrace`，同时累加真实 JSON 和 MessagePack 字节。

## 4. AgentMessage 字段

| 字段 | 作用 |
| --- | --- |
| `protocol_version` | 当前固定为 `1.0` |
| `message_id` | 单条消息 UUID |
| `task_id` | 所属任务 |
| `parent_message_id` | 上游因果消息 |
| `correlation_id` | 同一任务链路关联 ID |
| `sender` / `receiver` | 发送与接收方 |
| `action` | 请求动作 |
| `parameters` | JSON 兼容参数 |
| `result_ref` | 大结果本地引用 |
| `capability_required` | 接收方必须具备的能力 |
| `confidence` | 0～1 置信度 |
| `evidence_ids` | 证据链 |
| `semantic_state_ids` | 非文本状态引用 |
| `status` | 消息状态 |
| `error_code` | 稳定错误码 |
| `created_at` | UTC 时间 |

## 5. action 枚举

当前动作：`handshake`、`capability_exchange`、`plan_task`、`retrieve_evidence`、`execute_action`、`review_result`、`task_complete`。

## 6. status 枚举

`pending`、`accepted`、`completed`、`failed`。

## 7. error code

`none`、`agent_not_found`、`capability_mismatch`、`action_not_accepted`、`invalid_parameters`、`execution_failed`、`timeout`。

## 8. correlation_id

一次任务中的消息使用 task ID 作为 correlation ID，便于把 handshake、计划、检索、执行和审查串成同一条链。

## 9. parent_message_id

业务请求记录直接上游消息 ID，形成因果链；首条计划请求没有 parent，后续检索、执行、审查和完成消息逐级引用。

## 10. capability discovery

Orchestrator 通过 `require_capability(capability, action)` 发现 Agent。没有能力或不接受 action 时抛出稳定 RegistryError 子类。

## 11. handshake

每个注册 Agent 为任务生成一条自发自收的 handshake，内容包含 capabilities、accepted actions、输入输出模型和允许工具，用于记录当次运行的能力快照。

## 12. JSON 序列化

`to_json_bytes()` 使用 Pydantic JSON 输出并编码为 UTF-8。它用于互操作和精确字节统计。

## 13. MessagePack 序列化

`to_msgpack_bytes()` 对 JSON 模式字典使用 `use_bin_type=True` 打包；`from_msgpack_bytes()` 解码为 mapping 后重新经过 Pydantic 验证。

## 14. result_ref

启用时，计划、证据、执行和审查结果保存在进程内 `_result_refs`，消息传递 `result:<task_id>:<kind>`。关闭时传递完整 `task_plan`、`evidence_bundle`、`execution_result` 和 `review_result`。阶段三真实结果显示，关闭引用后平均 JSON 字节从 7621.433 增至 14363.767。

## 15. evidence_id

Retriever 生成稳定证据 ID；Executor 必须沿用；Reviewer 检查执行证据是否存在于 EvidenceBundle，未知证据会导致审查失败。

## 16. semantic_state_id

消息只携带状态 ID 列表。StateStore 根据 ID 读取二进制数据；参数中不得包含向量数组或 embedding 字符串。

## 17. 消息大小统计

ProtocolTrace 在 append 时计算两种序列化长度。MetricsWriter 另外统计文本字符、协议消息、状态字节、引用次数和完整结果传输次数。

## 18. 兼容性与版本

收到非 `1.0` 协议版本时模型验证失败。未来新增可选字段应保持旧消费者可忽略；破坏性变更需要提升协议版本并提供迁移策略。

## 19. 失败与重试

Registry 校验在投递前发生。LLM/Embedding HTTP 客户端只对受控请求进行有限重试并累计 retry count；最终失败进入任务失败记录和 Benchmark 原始数据。

## 20. 当前模型的示例消息

```json
{
  "protocol_version": "1.0",
  "task_id": "task-example",
  "parent_message_id": null,
  "correlation_id": "task-example",
  "sender": "planner",
  "receiver": "retriever",
  "action": "retrieve_evidence",
  "parameters": {
    "plan_ref": "result:task-example:plan",
    "current_step": "1",
    "task_topic": "enterprise-rag",
    "reused_memory_ids": []
  },
  "result_ref": "result:task-example:plan",
  "capability_required": ["knowledge_retrieval"],
  "confidence": 1.0,
  "evidence_ids": [],
  "semantic_state_ids": ["state-id-example"],
  "status": "accepted",
  "error_code": "none"
}
```

运行时还会自动生成 `message_id` 和 `created_at`。

