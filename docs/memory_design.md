# 共享记忆设计

## 1. 定义与聊天历史的区别

共享记忆是经过验证、可跨任务检索的长期知识；聊天历史只是当前会话上下文。MemLink 不把所有消息自动当记忆，只有完成结果或 Reviewer 允许的结果才进入仓库。

## 2. 记忆类型

`fact`、`evidence`、`strategy`、`success_experience`、`failure_experience`。当前编排器主要写入 `success_experience`，数据模型已支持其他类型。

## 3. SQLite 数据模型

`memories` 表保存 ID、主题、来源、类型、摘要、内容、标签 JSON、证据 JSON、状态 ID、置信度、使用次数、内容哈希和时间戳，并为主题和置信度建立索引。

## 4. 核心字段

- `memory_id`：UUID；
- `task_topic`：跨任务关联主题，如 `enterprise-rag`；
- `source_agent`：当前写入来源为 reviewer；
- `summary`：供 Planner/Retriever 快速复用的短摘要；
- `evidence_ids`：支撑经验的证据；
- `semantic_state_id`：可选的记忆向量状态；
- `confidence`：0～1；
- `usage_count`：真实被返回的次数。

## 5. 关键词检索

对 task topic、summary 和 content 使用参数化 `LIKE`，并按置信度和更新时间排序。

## 6. 标签检索

标签在 Python 中标准化为小写集合，按交集比例评分，避免依赖可选 SQLite JSON 扩展。

## 7. 向量检索

加载关联 SemanticState，校验维度后计算余弦相似度。损坏或缺失状态会记录 warning 并跳过该记忆。

## 8. 跨任务复用

### 企业 RAG

1. “RAG 服务响应变慢”完成后保存排查与止损经验；
2. “高并发下 RAG 请求超时”使用同一 `enterprise-rag` topic 命中经验；
3. “生成阶段延迟升高”继续复用主题、证据和策略。

### 企业 API

1. “API 频繁返回 500”形成经验；
2. “数据库连接池耗尽”复用依赖和资源排查策略；
3. “异步任务积压”复用前序监控、回滚和验证思路。

两组使用不同 topic，不会依赖另一组的记忆。

## 9. 命中统计

MemoryStore 分别统计查询总数、发生命中的查询数、返回记忆条数和复用 ID。`memory_hit_rate` 使用“有结果的查询次数/查询次数”，最大为 100%。

## 10. 重复记忆去重

主题、类型、摘要和内容组成规范化负载并计算 SHA-256。哈希重复时不新增行，而是合并标签、证据，取更高置信度并保留已有状态 ID。

## 11. 失败经验复用

数据模型支持 `failure_experience`，但当前成功路径不会自动生成失败经验，避免把未审查异常变成长期知识。后续可由 Reviewer 明确分类后写入。

## 12. 连接与并发

每次操作使用短连接和 `RLock`；context manager 在成功时 commit、异常时 rollback，并始终 close。它适合当前单机并发，不等同于分布式数据库。

## 13. 当前限制

没有全文索引、复杂价值评分、过期清理、加密、多租户和分布式一致性。向量检索为内存逐条比较，适用于 MVP 数据规模。

