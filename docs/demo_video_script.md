# MemLink 3～5 分钟演示视频脚本

建议总时长约4分30秒。正式录制前先运行 pytest、准备 `benchmarks/results/`，并使用 Fake 模式，避免网络和余额风险。

## 0:00–0:20 背景与痛点

- 屏幕：README 标题与一句话介绍。
- 讲解：普通多 Agent 经常重复传递长 Prompt，缺少能力发现、非文本状态、跨任务记忆和公平实验。
- 点击：不操作。
- 应看到：MemLink 项目简介。
- 避免：不要声称已经在 openEuler 实机通过。

## 0:20–0:50 架构与四个 Agent

- 屏幕：Streamlit 顶部项目概览，随后切到架构图。
- 讲解：Planner 规划、Retriever 找证据、Executor 只运行白名单工具、Reviewer 校验证据并决定记忆。
- 点击：展开一个 Agent 说明。
- 应看到：四个角色及双模式、SemanticState、共享记忆。
- 避免：不要说四个 Agent 只是四个相同 Prompt。

## 0:50–1:30 text 模式

- 屏幕：任务演示标签页，选择企业 RAG 第一个任务和 text。
- 讲解：text 是公平基线，四步传递完整自然语言，不使用 MessagePack。
- 点击：运行四 Agent 协作，依次展开 Agent 卡片。
- 应看到：四条轨迹、最终答案、协议消息和 MessagePack 为0。
- 避免：不要展示环境变量或 `.env`。

## 1:30–2:20 structured 模式

- 屏幕：切换 structured，保持同一任务并启用三个开关。
- 讲解：Registry 校验 capability/action，协议记录 handshake、证据 ID、状态 ID 和结果引用。
- 点击：再次运行，查看通信指标和 Reviewer 结果。
- 应看到：9条协议消息、JSON/MessagePack、result_ref、证据链。
- 避免：不要宣称 structured 在当前实验中更快。

## 2:20–2:50 SemanticState 与共享记忆

- 屏幕：SemanticState 表格，再运行同组第二个任务并看共享记忆。
- 讲解：页面只展示 state ID、维度、dtype、字节和哈希；向量没有转成文本。后续同 topic 任务命中 SQLite 记忆并增加 usage count。
- 点击：切换两个子标签。
- 应看到：状态元数据、memory ID、摘要、类型、置信度和使用次数。
- 避免：不要打印完整向量或数据库内容。

## 2:50–3:30 Benchmark

- 屏幕：Benchmark 标签页。
- 讲解：阶段三真实运行五配置×60任务，共300条，全部成功。完整 structured 的 JSON 均值比 text 低5.13%，但字符、Token 和耗时更高；关闭 result_ref 后 JSON 增加88.47%。
- 点击：依次展示 P50/P95、字符/Token、序列化和记忆命中率图。
- 应看到：来自真实 JSON 的表格和图表。
- 避免：不要把 MessagePack 和 JSON 同时存在误说成总字节下降。

## 3:30–4:00 openEuler

- 屏幕：`docs/openEuler_deployment.md` 和 Linux 脚本。
- 讲解：脚本覆盖环境创建、测试、Demo、API、Streamlit 和 Benchmark；当前状态为待 openEuler 24.03-LTS-SP3 实机验证。
- 点击：展示精确命令。
- 应看到：相对路径、`.venv`、LF 脚本。
- 避免：在没有真实日志时不要展示“通过”字样或伪造终端。

## 4:00–4:30 创新与总结

- 屏幕：技术报告创新点与发布清单。
- 讲解：核心价值是可切换、可验证、可量化，而不是只做聊天 UI；现有数据如实呈现收益和开销。
- 点击：回到 Streamlit 概览。
- 应看到：完整作品链路。
- 避免：不要使用未经实验支持的性能百分比。

