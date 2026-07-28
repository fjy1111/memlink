# Benchmark 方法

## 1. 实验问题

1. text 与完整 structured 在通信量、状态、记忆和耗时上有何差异？
2. 关闭共享记忆、SemanticState 或 result_ref 后，哪些指标真实变化？
3. 连续运行十轮时是否出现失败、资源残留或状态异常增长？

## 2. 对照变量

同一次正式实验固定任务数据与顺序、Fake LLM、Fake Embedding、temperature=0、随机种子 2026、初始空记忆、10轮、60秒超时和最多2次重试。每种配置使用独立临时 SQLite、StateStore 和指标目录。

## 3. text 基线

四个 Agent 顺序传递完整自然语言。它不创建 AgentMessage，协议消息数和 MessagePack 字节为0。共享记忆可用，但不传递 SemanticState。

## 4. structured 完整方案

启用 AgentRegistry、handshake、结构化 action、MessagePack、共享记忆、SemanticState 和 result_ref。

## 5. 消融配置

| 名称 | 关闭内容 | 实际分支 |
| --- | --- | --- |
| `structured_no_memory` | 共享记忆 | 不查询、不命中、不写入 SQLite 记忆 |
| `structured_no_semantic_state` | SemanticState | 不生成向量文件，不传递状态 ID |
| `structured_no_result_ref` | result_ref | 消息传递完整计划、证据、执行和审查结果 |

`ablation` 选择器执行 text、完整 structured 和三个消融配置。

## 6. 任务数据

数据来自 `data/examples/continuous_tasks.json`：

- 企业 RAG：响应变慢、高并发超时、生成阶段延迟；
- 企业 API：HTTP 500、连接池耗尽、异步任务积压。

顺序固定为 `rag-1`、`rag-2`、`rag-3`、`api-1`、`api-2`、`api-3`。

## 7. 运行轮数

五种配置各执行10轮，每轮6个真实任务，因此正式结果包含 `5 × 10 × 6 = 300` 条原始记录。完整 structured 的60条记录同时用于稳定性汇总。

## 8. Fake 模型可复现性

Fake LLM 根据角色和输入契约返回确定性 Pydantic 结果。Fake Embedding 使用 SHA-256 派生并归一化向量。它们不访问网络，不消耗模型余额，适合回归和公平对比。

## 9. 模型后端边界

正式 Benchmark 入口固定使用 Fake LLM 与 Fake Embedding，不接受 DeepSeek
后端，也不访问互联网。DeepSeek 只用于 CLI、API 和 Streamlit 的人工真实模型
演示；不建议用真实模型直接重跑现有 300 条正式记录。pytest 中的 DeepSeek
协议测试使用 `httpx.MockTransport`，不会调用真实 API。

## 10. 指标定义

- `message_count`：text 消息或 structured ProtocolTrace 消息数；
- `protocol_message_count`：结构化消息数；
- `text_character_count`：text content 字符，或 structured 消息所有字符串字段字符；
- `estimated_token_count`：统一使用 `ceil(character_count / 4)`；
- JSON/MessagePack 字节：实际 UTF-8/MessagePack 序列化长度；
- SemanticState：状态 ID 传输次数和被引用向量原始字节；
- memory hit rate：有结果的查询次数/查询总数；
- repeated retrieval：多检索策略返回的重复 memory ID 数；
- result reference/full result：引用和完整结果字段次数；
- total duration：单任务编排墙钟耗时。

## 11. P50/P95

排序后使用线性插值：位置为 `(n-1) × percentile / 100`，上下位置不同则按小数部分插值。该函数有空输入、范围、单值、P50/P95 单元测试。

## 12. 环境信息

正式 Windows 结果采集于2026-07-27，使用 CPython 3.11.15、Windows-10-10.0.26200-SP0、AMD64、6逻辑 CPU。环境文件不复制环境变量或密钥。

## 13. 原始数据

`raw_runs.jsonl` 和 UTF-8-SIG `raw_runs.csv` 保存每个任务。记录包含 run ID、实验、任务组、轮次、成功状态、全部通信指标、Agent 耗时、SQLite/状态文件前后计数、时间戳、Python 和操作系统。

## 14. 统计方法

按实验配置分组，对数值指标计算均值、最小、最大、P50、P95和总体标准差；另外计算完成率、错误率和平均记忆查询命中率。汇总可从 JSONL 重新生成。

## 15. 输出

运行时输出包括原始 JSONL/CSV、汇总 JSON/CSV、消融 CSV、稳定性 JSON、环境 JSON 和自动 Markdown 报告。目录默认被 Git 忽略，本仓库只提交方法和经核验的文字分析。

## 16. 实验局限

Fake 模型不代表真实厂商推理时延和 tokenizer；当前任务规模较小；Windows 文件系统和 SQLite 性能不能替代 openEuler 实测；structured 字符统计包含协议字符串，因此不能直接等价为自然语言 Prompt Token。
