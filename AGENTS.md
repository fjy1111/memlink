# MemLink 项目 Codex 开发总指令

## 1. 项目背景

本项目用于参加“第三届中国研究生操作系统开源创新大赛”应用创新赛道第 10 题：

**一种面向多智能体协作的低开销通信、状态传递与共享记忆机制**

项目名称：**MemLink**

项目目标不是制作一个普通的多 Agent 聊天 Demo，而是实现一套可运行、可测试、可量化比较的多智能体协作基础设施。

最终系统至少包含：

- Planner Agent：任务规划与拆解
- Retriever Agent：知识与历史记忆检索
- Executor Agent：工具执行与结果生成
- Reviewer Agent：结果审查、证据校验与最终输出

系统必须同时支持：

1. 纯文本通信模式；
2. 结构化协议通信模式；
3. 非文本语义状态传递；
4. 跨任务共享记忆；
5. 可复现 Benchmark；
6. Windows 开发与 openEuler 24.03-LTS-SP3 部署。

---

## 2. 当前开发环境

- Windows 10/11
- 项目路径：`E:\memlink`
- PyCharm
- Conda 环境：`memlink`
- Python 3.11
- 最终部署环境：openEuler 24.03-LTS-SP3 x86_64
- 代码主要由 Codex 辅助完成
- Git 用于保留完整开发过程
- ## Windows解释器约束

Windows开发与测试必须使用以下Conda解释器：

D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe

不得在Windows项目目录中创建或使用`.venv`。

所有Windows命令应显式使用：

D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m <module>

openEuler部署时才在Linux项目目录创建`.venv`。

所有业务代码必须兼容 Windows 和 Linux。

---

## 3. 总体开发原则

1. 优先完成可运行、可演示、可测试的 MVP。
2. 只分四个阶段，不额外拆成大量小阶段。
3. 每个阶段必须形成独立可运行成果。
4. 不得一次性生成大量未经测试的代码。
5. 每完成一个阶段，必须实际运行测试。
6. 不得伪造测试结果。
7. 不得删除已有测试来绕过失败。
8. 所有配置通过环境变量和 `pydantic-settings` 管理。
9. 文件路径统一使用 `pathlib.Path`。
10. 禁止写死 `C:\`、`D:\`、`E:\` 等 Windows 路径。
11. 禁止依赖 `pywin32` 等 Windows 专属库。
12. Linux 脚本必须使用 LF 换行符。
13. 所有核心模块必须带类型注解、日志和异常处理。
14. 测试中不得真实调用付费模型 API，必须使用 Fake/Mock LLM。
15. 所有性能数据必须保存为 JSON 或 CSV。
16. 每次修改后必须列出修改文件、运行命令、测试结果和 Git 提交建议。
17. 核心功能完成前，不做复杂前端和过度美化。
18. 优先使用简单、稳定、跨平台的技术，不引入不必要的中间件。
19. 不要在项目初期引入 Kubernetes、eBPF、自定义内核调度器或复杂分布式集群。
20. 任何可能破坏现有代码、批量删除文件、重置 Git 历史的操作都必须先说明。

---

## 4. 技术路线

### 核心技术

- FastAPI：API 服务
- Pydantic v2：结构化协议和数据校验
- pydantic-settings：配置管理
- LangGraph 或轻量自定义状态机：多 Agent 编排
- SQLite：任务、消息和记忆元数据
- NumPy：向量保存和余弦相似度计算
- MessagePack：结构化消息的紧凑序列化
- pytest：自动化测试
- httpx：API 测试
- Streamlit：仅在核心功能完成后用于快速演示
- OpenAI-compatible API：真实模型调用适配器
- Fake LLM：测试和离线演示

### 不作为 MVP 必需项

以下内容只能在四个阶段全部完成且时间充足时增加：

- Redis
- Milvus
- Docker 沙箱
- Prometheus/Grafana
- 多机通信
- eBPF
- 真正的模型隐藏层状态传递

---

## 5. 系统核心模式

### 5.1 纯文本基线模式

Agent 之间传递完整自然语言文本。

例如：

```text
Planner -> Retriever：完整任务描述和规划文本
Retriever -> Executor：完整检索文档和长摘要
Executor -> Reviewer：完整执行过程和结果
```

该模式用于建立 Benchmark 基线。

### 5.2 结构化协议模式

Agent 之间传递统一结构化消息：

```python
class AgentMessage(BaseModel):
    message_id: str
    task_id: str
    sender: str
    receiver: str
    action: str
    parameters: dict
    result_ref: str | None
    capability_required: list[str]
    confidence: float
    evidence_ids: list[str]
    created_at: datetime
```

需要支持：

- Agent 注册；
- 能力声明；
- 能力发现；
- 动作类型；
- 参数传递；
- 结果引用；
- 错误码；
- 消息追踪。

### 5.3 非文本状态传递

非文本状态不能只是把 embedding 转成字符串放入 Prompt。

推荐实现：

1. Retriever 生成或获得 embedding；
2. embedding 以 NumPy 数组或二进制形式保存在 StateStore；
3. 系统生成 `semantic_state_id`；
4. 下游 Agent 只接收状态 ID 和必要元数据；
5. 下游 Agent 按需读取向量，用于相似度计算、检索或路由；
6. Benchmark 记录状态传输次数和字节数。

示例模型：

```python
class SemanticState(BaseModel):
    state_id: str
    task_id: str
    source_agent: str
    semantic_type: str
    vector_size: int
    storage_ref: str
    metadata: dict
```

### 5.4 共享记忆

共享记忆不是普通聊天历史。

至少支持：

- 事实记忆；
- 证据记忆；
- 策略记忆；
- 成功经验；
- 失败经验。

每条记忆至少包含：

```python
class SharedMemory(BaseModel):
    memory_id: str
    task_topic: str
    source_agent: str
    memory_type: str
    summary: str
    evidence_ids: list[str]
    confidence: float
    usage_count: int
    created_at: datetime
```

支持：

- 关键词检索；
- 标签检索；
- 向量相似度检索；
- 后续任务复用；
- 命中次数统计；
- 记忆价值评分；
- 重复记忆合并。

---

# 6. 四阶段开发计划

## 阶段一：项目骨架与纯文本基线

### 目标

在 Windows 上完成可运行的最小系统，建立纯文本通信基线。

### 必须完成

1. 创建标准项目目录。
2. 配置 FastAPI。
3. 配置 `pydantic-settings`。
4. 创建统一日志模块。
5. 定义 Task、Agent、Message、Result 数据模型。
6. 实现 Planner、Retriever、Executor、Reviewer 四个 Agent 的统一接口。
7. 实现纯文本顺序协作流程。
8. 提供 Fake LLM，保证无 API Key 也能运行。
9. 创建一个“企业技术故障分析”示例任务。
10. 提供健康检查接口和任务执行接口。
11. 完成 pytest 基础测试。
12. 创建 README、`.env.example`、`.gitignore`、`.gitattributes`。
13. 保存基础运行指标：耗时、消息数、字符数、估算 Token 数。

### 推荐目录

```text
memlink/
├─ app/
│  ├─ agents/
│  ├─ api/
│  ├─ core/
│  ├─ models/
│  ├─ runtime/
│  ├─ protocol/
│  ├─ memory/
│  ├─ state/
│  ├─ benchmark/
│  └─ main.py
├─ tests/
├─ benchmarks/
├─ scripts/
│  ├─ windows/
│  └─ linux/
├─ docs/
├─ data/
├─ .env.example
├─ .gitignore
├─ .gitattributes
├─ requirements.txt
├─ requirements-dev.txt
├─ pyproject.toml
├─ AGENTS.md
└─ README.md
```

### 阶段一完成标准

以下命令必须成功：

```powershell
python -m pytest -q
python -m uvicorn app.main:app --reload
```

至少提供：

- `GET /health`
- `POST /api/v1/tasks/run`
- `GET /api/v1/tasks/{task_id}`

### 阶段一建议 Git 提交

```text
feat: build MemLink text-mode multi-agent MVP
```

---

## 阶段二：结构化通信、语义状态与共享记忆

### 目标

完成赛题最核心的三个机制，并同时保留纯文本模式。

### 必须完成

1. 实现 Agent 注册中心。
2. 实现能力发现。
3. 实现结构化 AgentMessage 协议。
4. 使用 MessagePack 统计序列化字节数。
5. 支持 `text` 和 `structured` 两种通信模式切换。
6. 实现 StateStore。
7. 实现 SemanticState 非文本向量状态。
8. 实现 SQLite 共享记忆仓库。
9. 实现关键词、标签和向量相似度检索。
10. 实现历史记忆复用。
11. 设计两组有关联性的连续任务。
12. 保存证据链。
13. 增加失败重试、超时和状态追踪。
14. 补充完整单元测试和集成测试。

### 第一组连续任务

企业 RAG 服务故障：

1. RAG 服务响应变慢；
2. 高并发下请求超时；
3. 检索正常但生成阶段延迟升高。

### 第二组连续任务

API 服务故障：

1. 接口频繁返回 500；
2. 数据库连接池耗尽；
3. 异步任务堆积。

后续任务必须能够复用前面任务形成的策略、证据或排查流程。

### 阶段二完成标准

必须能分别执行：

```powershell
python -m app.cli run-demo --mode text
python -m app.cli run-demo --mode structured
```

并输出：

- 最终答案；
- Agent 执行轨迹；
- 消息数量；
- 文本字符数；
- 估算 Token 数；
- 结构化消息字节数；
- 非文本状态传递次数；
- 非文本状态字节数；
- 共享记忆命中数量；
- 总耗时。

### 阶段二建议 Git 提交

```text
feat: add structured protocol semantic state and shared memory
```

---

## 阶段三：Benchmark 与 openEuler 部署

### 目标

证明结构化方案相较纯文本方案确实有效，并确保比赛环境可运行。

### 必须完成

1. 创建统一 Benchmark Runner。
2. 在相同任务、相同模型、相同配置下比较两种模式。
3. 每个任务重复运行多次。
4. 输出 JSON 和 CSV。
5. 统计：
   - 消息数量；
   - 字符数；
   - 估算 Token 数；
   - 序列化大小；
   - 非文本状态传递次数；
   - 总耗时；
   - P50/P95 耗时；
   - 记忆命中率；
   - 重复检索次数；
   - 任务完成率；
   - 错误和重试次数。
6. 增加消融实验：
   - 关闭共享记忆；
   - 关闭非文本状态；
   - 关闭结果引用；
   - 完整结构化方案。
7. 连续运行至少 10 轮任务。
8. 编写 `scripts/linux/setup.sh`。
9. 编写 `scripts/linux/start.sh`。
10. 编写 `scripts/linux/test.sh`。
11. 编写 openEuler 部署文档。
12. 在 openEuler 24.03-LTS-SP3 中实际执行 pytest 和演示流程。
13. 修复大小写、路径、换行符和依赖兼容问题。

### Benchmark 结果文件

```text
benchmarks/results/
├─ text_mode_results.json
├─ structured_mode_results.json
├─ ablation_results.json
├─ benchmark_summary.csv
└─ environment.json
```

### 不得虚构目标数值

不得预先写死“Token 降低 40%”等结论。

必须根据实际实验数据生成结论。如果性能没有提升，应分析原因并优化，不能伪造结果。

### 阶段三建议 Git 提交

```text
test: add reproducible benchmark and openEuler deployment
```

---

## 阶段四：演示界面与比赛交付

### 目标

完成可以提交和答辩的作品。

### 必须完成

1. 创建简单清晰的 Streamlit 演示页面。
2. 页面支持输入复杂任务。
3. 页面支持选择 `text` 或 `structured` 模式。
4. 展示四个 Agent 的执行轨迹。
5. 展示结构化消息。
6. 展示共享记忆命中情况。
7. 展示证据链和最终答案。
8. 展示 Benchmark 对比图。
9. 完善 README。
10. 完成系统设计文档。
11. 完成部署文档。
12. 完成测试报告。
13. 完成技术报告初稿。
14. 生成答辩素材说明。
15. 给出 3～5 分钟视频录制脚本。
16. 创建最终 Release 检查清单。

### 最终交付物

```text
docs/
├─ architecture.md
├─ protocol_design.md
├─ memory_design.md
├─ benchmark_methodology.md
├─ openEuler_deployment.md
├─ test_report.md
├─ technical_report.md
├─ demo_video_script.md
└─ defense_questions.md
```

### 阶段四建议 Git 提交

```text
docs: complete competition delivery materials and demo
```

---

# 7. Codex 每次工作的固定输出格式

每次完成一个阶段或任务后，必须按以下格式回复：

## 本次完成内容

说明实际完成了什么。

## 新增文件

列出所有新增文件。

## 修改文件

列出所有修改文件。

## 核心技术

说明本次使用的技术和设计。

## 运行命令

分别给出 Windows 和 openEuler 命令。

## 实际测试结果

只能写真实执行过的测试结果。

## 当前问题

列出仍存在的问题、风险和未完成项。

## 我需要理解的知识

用新手能理解的语言解释本次核心知识。

## Git 提交建议

给出一条规范提交信息。

## 下一步

说明下一阶段准备做什么。

---

# 8. Codex 操作规则

当用户说“执行阶段一”时：

1. 先检查仓库当前文件。
2. 输出阶段一实施方案。
3. 直接开始创建和修改文件。
4. 安装缺失依赖前先说明依赖用途。
5. 实际运行测试。
6. 修复测试错误。
7. 测试通过后输出阶段总结。
8. 不要停留在只给建议而不写代码。

当用户说“继续阶段二”时：

1. 读取现有代码和阶段一结果。
2. 不推翻已有架构。
3. 补充结构化通信、语义状态和共享记忆。
4. 保持纯文本基线仍然可运行。
5. 实际运行两种模式。
6. 实际运行测试。
7. 输出阶段总结。

当用户说“继续阶段三”时：

1. 创建真实 Benchmark。
2. 不得伪造数据。
3. 生成 openEuler 部署脚本。
4. 检查所有跨平台风险。
5. 输出需要在 openEuler 中执行的命令。
6. 如果 Codex 当前无法访问 openEuler，明确标记哪些步骤必须由用户在虚拟机执行。
7. 用户返回日志后继续修复。

当用户说“继续阶段四”时：

1. 只在核心功能稳定后创建演示界面。
2. 生成完整文档。
3. 根据真实代码和真实实验结果写报告。
4. 不得编造不存在的功能或指标。
5. 输出比赛最终检查清单。

---

# 9. 质量底线

以下任何一项不满足，都不能宣布项目完成：

- 纯文本模式可运行；
- 结构化模式可运行；
- 至少四个 Agent 协同；
- 非文本状态真实存在；
- 共享记忆可以跨任务复用；
- 两组连续任务可以运行；
- Benchmark 可复现；
- 至少 10 轮连续执行；
- pytest 通过；
- openEuler 环境完成实际测试；
- README 和部署文档完整；
- 实验数据来自真实运行；
- Git 历史保留开发过程。

---

# 10. 第一条执行指令

读取本文件后，立即执行：

> 检查当前仓库。按照本文件“阶段一”的要求开始开发。先输出一个简短实施方案，然后直接创建项目骨架、安装必要依赖、实现纯文本多 Agent MVP、编写测试并实际运行。遇到错误自行定位和修复，不要只给我代码片段。完成后严格按照“Codex 每次工作的固定输出格式”汇报。不要进入阶段二。
