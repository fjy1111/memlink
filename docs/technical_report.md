# MemLink 技术报告

## 1. 摘要

MemLink 面向多智能体协作中的重复文本传输、角色边界模糊、非文本状态缺失和经验无法跨任务复用等问题，实现 text/structured 双模式、capability 驱动路由、SemanticState、SQLite 共享记忆和可消融 Benchmark。系统提供 FastAPI、CLI、Streamlit，并已完成 Windows 与 openEuler 实际验证。

## 2. 关键词

多智能体；结构化通信；MessagePack；语义状态；共享记忆；Benchmark；openEuler

## 3. 项目背景

赛题要求实现低开销通信、状态传递与共享记忆机制。项目不以聊天界面为核心，而以可运行基础设施、真实指标和可复现实验为交付目标。

## 4. 问题分析

普通 Prompt 多 Agent 常见问题包括：完整上下文逐步膨胀、接收方能力不可验证、结果与证据缺少引用、embedding 被文本化、历史经验和当前上下文混合、优化结论缺少公平基线。

## 5. 需求分析

系统必须支持四个真实角色、text 基线、structured 协议、二进制语义状态、跨任务记忆、离线 Fake 模型、真实模型可选入口、指标、消融、Windows 开发和 openEuler 部署。

## 6. 总体设计

TaskOrchestrator 是轻量状态机。入口创建 Task 后先检索记忆，再进入 text 或 structured 分支，最后保存通过审查的经验、原始指标和 TaskResult。Registry、StateStore、MemoryStore 和 MetricsWriter 是独立组件。

## 7. 多 Agent 设计

Planner 输出计划；Retriever 输出证据包；Executor 只调用白名单确定性工具；Reviewer 校验证据、执行结果和能力完成情况。四个角色拥有不同 Pydantic 输入输出、system prompt、capability、action 与权限。

## 8. 结构化通信协议

AgentMessage 使用协议版本、消息/任务/关联/父消息 ID、sender、receiver、action、参数、结果引用、能力、置信度、证据、语义状态、状态和错误码。ProtocolTrace 对 JSON 和 MessagePack 进行精确计量。

## 9. 非文本状态传递

EmbeddingClient 生成 NumPy 向量，StateStore 保存 `.npy` 和校验元数据。structured 消息只传递 state ID；检索时按需加载并计算余弦相似度。该机制不同于把向量列表拼进 Prompt。

## 10. 共享记忆

SQLiteSharedMemoryStore 保存主题、类型、摘要、证据、状态引用、置信度和使用次数。它支持关键词、标签和向量检索，并通过内容哈希合并重复经验。两组连续任务使用不同 task topic。

## 11. 系统实现

项目使用 Python 3.11、FastAPI、Pydantic v2、SQLite、NumPy、MessagePack、httpx、pytest 和 Streamlit。路径使用 pathlib，配置使用 pydantic-settings，日志使用统一模块。

## 12. API、CLI 与演示

FastAPI 提供健康、运行和查询接口；CLI 提供双模式 Demo 与 Benchmark；Streamlit 调用同一 TaskOrchestrator，展示 Agent 轨迹、通信指标、记忆、状态、Reviewer 信息和真实 Benchmark。

## 13. Benchmark 设计

五种配置使用相同任务、顺序、Fake 客户端、seed、轮数、温度、超时和重试。
每种配置有独立临时数据库与状态目录。每组10轮、每轮6个任务，正式 Windows
实验共产生300条记录。选择 Fake 是为了排除网络、计费和模型服务版本波动，
并保证离线复现；该 Benchmark 不调用 DeepSeek。

## 14. 实验结果

text 与 structured 均60/60成功。text P50/P95 为27.286/33.587 ms，完整
structured 为48.490/61.698 ms。structured JSON 均值低5.13%，但字符、估算
Token、总传输负载和耗时更高。

另有一次真实 DeepSeek structured 演示，模型为 `deepseek-v4-pro`，Planner、
Retriever、Executor、Reviewer 依次执行成功。结果为9条消息、估算 Token 1040、
JSON 7734 B、MessagePack 7002 B、SemanticState 3次/384 B、共享记忆命中15条、
总耗时28107.309 ms。约28秒主要包含外部网络和模型推理耗时，是功能验收记录，
不是性能 Benchmark。

## 15. 消融实验

关闭记忆后查询和 SQLite 增长为0；关闭 SemanticState 后状态传输和文件为0；关闭 result_ref 后完整结果字段平均7次，JSON 字节相对完整 structured 增加88.47%。开关都进入真实分支。

## 16. 稳定性测试

完整 structured 连续执行60个任务，成功60、失败0、异常0、重试0；数据库句柄释放、临时目录清理成功，未记录后台进程残留。

## 17. openEuler 适配

六个阶段三脚本和阶段四 UI 脚本使用 Bash、LF、严格模式、相对根目录和 Linux
`.venv`。已在 openEuler 24.03-LTS-SP3 x86_64、Python 3.11.6、
`/home/fjy/memlink/.venv/bin/python` 下实机验证：`pip check` 无损坏依赖，
pytest 为77 passed、1 warning、0 failed、0 errors。真实 DeepSeek 入口也已完成
人工验证。

## 18. 创新点

- 同一系统内保留可复现 text/structured 对照；
- capability 驱动 Agent 发现和 action 校验；
- JSON/MessagePack 双序列化实测；
- result_ref 可消融，验证重复结果传输变化；
- NumPy 二进制 SemanticState 与 ID 引用；
- SQLite 跨任务共享记忆和真实 usage count；
- 五配置可消融实验和原始数据保留；
- Windows/openEuler 双环境交付。

## 19. 与普通多 Agent 系统的区别

本项目不只把多个 Prompt 串联。角色契约、能力注册、消息动作、证据链、状态 ID、记忆仓库、工具白名单和实验指标都由代码模型约束，并可以通过测试观察。

## 20. 局限性

系统是单机进程内编排；结果引用表和 TaskStore 不持久化；SQLite 向量检索不是
大规模索引；Fake Token 不等同模型 tokenizer；单次 DeepSeek 结果不能替代多轮
Benchmark，也不能证明 structured 在所有任务中都更快；Streamlit 不提供生产级
认证。

## 21. 后续工作

可在保持接口兼容的前提下增加结果引用持久化、记忆过期和价值评分、批量向量检索、分布式状态后端、真实模型小规模对照和 openEuler 性能剖析。

## 22. 总结

MemLink 已形成从双模式 Agent 编排、状态和记忆，到可复现实验、演示页面和跨平台脚本的完整作品链路。现有数据同时呈现收益和开销，为后续优化提供了可核验基线。

最终结论明确区分：Fake 用于 pytest 与300条可复现 Benchmark；DeepSeek 用于
真实模型演示；Windows 用于开发与回归验证；openEuler 用于目标平台实机验收。
structured 的主要价值是协议约束、状态传递、结果引用、证据追踪和共享记忆，
而不是保证所有任务的字符、Token 或耗时都低于 text。
