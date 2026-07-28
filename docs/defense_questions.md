# 答辩问题与参考回答

## 1. 为什么不是普通 Prompt 多 Agent？

四个角色有不同 Pydantic 契约、capability、action、工具权限和输出验证；structured 还包含 Registry、证据链、状态 ID、结果引用和协议字节统计，不只是串联 Prompt。

## 2. 四个 Agent 有什么真实区别？

Planner 只规划；Retriever 只检索和排序证据；Executor 只能运行注册的确定性工具；Reviewer 校验证据、能力完成和执行状态，并决定是否保存记忆。

## 3. structured 模式为什么更高效？

不能笼统说所有指标更高效。当前结果中 JSON 字节较 text 低5.13%，result_ref 明显减少完整结果重复传输；但字符、Token、总负载和耗时更高。优势是边界、追踪和可选择传输，仍需继续优化。

## 4. MessagePack 有什么作用？

它把同一 AgentMessage 紧凑编码为二进制，并与 JSON 同时测量。当前完整 structured 的 MessagePack 均值6865.533 B，小于其 JSON 7621.433 B。

## 5. SemanticState 是不是把 embedding 转成文本？

不是。向量保存在 `.npy`，消息只传 state ID。页面只显示元数据，向量不会进入 Prompt 或协议参数。

## 6. 向量如何传递和使用？

StateStore 保存向量并返回 UUID；消息携带 UUID；下游按需加载、校验维度/dtype/哈希，再用于共享记忆余弦相似度检索。

## 7. 共享记忆与聊天历史有什么区别？

聊天历史属于当前会话；共享记忆是经 Reviewer 或完成状态验证、可跨任务查询、带证据、置信度和使用次数的长期记录。

## 8. 如何证明记忆被复用？

连续任务使用相同 task topic。结果返回 reused memory IDs，数据库 usage count 增长，原始指标记录查询、命中和重复检索。关闭记忆后这些值和数据库增长均为0。

## 9. 如何保证两种模式公平比较？

使用同一任务文件、顺序、Fake 客户端、seed、temperature、轮数、超时和重试配置；每种配置从独立空数据库和状态目录开始。

## 10. 为什么使用 Fake LLM 做 Benchmark？

它消除费用、网络波动和服务版本变化，确保离线可复现。DeepSeek 入口仅用于
人工真实模型演示，不是自动测试或 Benchmark 条件。

## 11. 是否支持 DeepSeek 和阿里百炼？

项目当前只接入 DeepSeek Chat Completions，不提供多供应商切换。DeepSeek
已在 Windows 和 openEuler 完成人工真实验证，演示模型为 `deepseek-v4-pro`；
SemanticState 在 DeepSeek 演示中使用可复现 Fake Embedding。密钥只从被忽略的
`.env` 读取，不进入页面输入、日志或结果；pytest 使用 MockTransport，不调用
真实服务。

## 12. 为什么不用 Redis 或 Milvus？

当前目标是单机可演示、可复现 MVP。SQLite 和 NumPy 足以验证机制，依赖更少，更适合 Windows/openEuler。大规模场景可通过现有 Store 接口替换。

## 13. 为什么使用 SQLite？

它跨平台、零服务部署、支持事务和参数化查询，适合当前共享记忆元数据规模，也便于每个 Benchmark 实验创建独立临时数据库。

## 14. result_ref 的价值是什么？

它用短引用代替计划、证据、执行和审查对象。消融中关闭引用后完整字段平均7次，JSON 较完整 structured 增加88.47%。

## 15. structured 模式有哪些额外开销？

四条 handshake、协议字段、Registry 校验、MessagePack 编码、SQLite 多策略查询、状态文件和哈希校验。当前 P50/P95 高于 text，报告已如实记录。

## 16. openEuler 适配做了什么？

脚本使用 Bash 严格模式、LF、相对根目录、Linux `.venv`、UTF-8、权限检查，
并覆盖 pytest、Demo、API、UI、Benchmark 和环境采集。已在 openEuler
24.03-LTS-SP3 x86_64、Python 3.11.6、
`/home/fjy/memlink/.venv/bin/python` 下实机验证；`pip check` 无损坏依赖，
pytest 为77 passed、1 warning、0 failed、0 errors。

## 17. 项目与操作系统赛道有什么关系？

项目关注协作基础设施的通信表示、状态存储、持久化、资源生命周期、跨平台进程和文件管理，并通过可复现实验量化系统开销，而不是只展示模型内容。

## 18. 如何保证工具执行安全？

Executor 只能调用 ToolRegistry 中允许角色为 executor 的两个确定性工具。没有 Shell、Python eval 或任意命令入口；页面也不执行 Shell。

## 19. 当前项目最大局限是什么？

单机进程内结果引用和 TaskStore 不适合分布式恢复；SQLite 向量检索不是大规模
索引；当前 structured 固定开销在轻量 Fake 任务中较明显；单次真实模型结果受
网络和服务负载影响，不能替代多轮 Benchmark。

## 20. 后续如何扩展为分布式系统？

保持 Agent、Registry、StateStore、MemoryStore 接口，逐步替换为带认证的服务端注册、对象存储、持久结果引用和分布式记忆后端，并增加幂等、租约、追踪和一致性策略。

## 21. 真实 DeepSeek 为什么约28秒？能说明 structured 更慢吗？

不能直接下这个结论。该次 `deepseek-v4-pro` structured 演示耗时28107.309 ms，
包含四个 Agent 的外部网络请求和模型推理。它证明真实接入、JSON 协议、
SemanticState、result_ref 和共享记忆能够共同运行，但只是单次功能记录。
text/structured 的可复现比较应看使用相同 Fake 后端、相同任务和相同配置的
300条 Benchmark，并如实承认现有 structured 在部分指标上开销更高。

## 22. 如何保证 API Key 不泄露？

API Key 只从被 Git 忽略的项目根目录 `.env` 读取；`.env.example` 只有占位符。
页面和输出只显示“API Key 已配置/未配置”，日志不记录 Authorization、完整
Prompt 或完整响应。发布时不提交 `.env`、SQLite 数据库、`.npy` 状态、原始密钥
或包含密钥的日志。
