# MemLink

MemLink 是面向多智能体协作的低开销通信、状态传递与共享记忆基础设施。本仓库当前完成 **阶段一：项目骨架与纯文本基线**。

## 阶段一能力

- FastAPI 服务及环境变量配置；
- Planner、Retriever、Executor、Reviewer 四个 Agent 的统一异步接口；
- 固定顺序的纯文本完整上下文传递；
- 无需 API Key、不会访问网络的确定性 Fake LLM；
- 企业技术故障分析示例；
- 任务执行、查询及健康检查 API；
- 每次运行将耗时、消息数、字符数和估算 Token 数保存为 JSON。

结构化协议、非文本语义状态、共享记忆和正式 Benchmark 属于后续阶段，本阶段没有提前实现。

## 环境要求

- Python 3.11 或更高版本；
- Windows 10/11，或兼容 Python 3.11 的 Linux（目标为 openEuler 24.03-LTS-SP3）。

## Windows 启动

```powershell
conda activate memlink
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m uvicorn app.main:app --reload
```

服务默认位于 `http://127.0.0.1:8000`，交互文档位于 `http://127.0.0.1:8000/docs`。

## openEuler 启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

阶段一仅提供跨平台命令，openEuler 自动化部署脚本将在阶段三实现。

## API 示例

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

执行示例任务：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/run \
  -H "Content-Type: application/json" \
  -d '{"title":"企业技术故障分析","prompt":"订单服务响应变慢并出现少量 HTTP 500，请给出排查建议。"}'
```

响应中的 `task_id` 可用于查询：

```bash
curl http://127.0.0.1:8000/api/v1/tasks/<task_id>
```

示例请求保存在 `data/examples/enterprise_incident.json`。运行指标默认写入 `data/metrics/<task_id>.json`。

## 配置

复制 `.env.example` 为 `.env`。所有设置使用 `MEMLINK_` 前缀：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MEMLINK_APP_NAME` | `MemLink` | API 服务名 |
| `MEMLINK_APP_VERSION` | `0.1.0` | API 版本 |
| `MEMLINK_ENVIRONMENT` | `development` | 环境标识 |
| `MEMLINK_LOG_LEVEL` | `INFO` | 日志等级 |
| `MEMLINK_METRICS_DIR` | `data/metrics` | JSON 指标目录 |

相对路径会以项目根目录为基准解析，避免依赖启动命令所在目录。

## 纯文本协作流程

```text
用户任务
  -> Planner：拆解故障排查步骤
  -> Retriever：补充内置故障分析知识
  -> Executor：生成可执行诊断和止损动作
  -> Reviewer：审查证据并形成最终报告
```

Agent 之间传递完整自然语言文本。这是后续比较结构化通信开销的可复现基线。
