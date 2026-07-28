# MemLink 最终测试与验证报告

## 1. 测试环境

Windows 开发验证：

- 系统：Windows-10-10.0.26200-SP0，AMD64；
- 解释器：`D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe`；
- Python：3.11.15，Anaconda 构建。

openEuler 实机验证：

- 系统：openEuler 24.03-LTS-SP3 x86_64；
- 解释器：`/home/fjy/memlink/.venv/bin/python`；
- Python：3.11.6。

自动测试和 Benchmark 使用 Fake LLM/Fake Embedding，不访问付费 API。DeepSeek
仅在人工真实演示中使用。

## 2. 测试范围

覆盖领域模型、四 Agent 契约、Registry、协议序列化、LLM/Embedding 适配器、StateStore、SQLite MemoryStore、双模式编排、API、CLI、Benchmark、消融、稳定性、Linux 脚本和 Streamlit 展示层。

## 3. 单元测试

验证 Pydantic 字段约束、唯一 ID、token 估算、Fake 模型确定性、MessagePack round trip、状态哈希、余弦检索、记忆去重、P50/P95 和总体标准差。

## 4. 集成测试

验证四 Agent 顺序执行、structured capability 路由、真实跨任务记忆复用、SemanticState 文件与 ID 传递、任务结果持久查询和 Reviewer 审查字段。

## 5. API 测试

pytest 使用 FastAPI TestClient 覆盖 health、text/structured POST、GET 查询、404和422。第四阶段另启动真实 Uvicorn：

- `GET /health`：200；
- `POST /api/v1/tasks/run`：text 与 structured 均为201；
- `GET /api/v1/tasks/{task_id}`：两个任务均为200、状态 completed；
- 验证后8000端口和项目 Uvicorn 进程：0。

## 6. CLI 测试

pytest 在隔离目录中使用当前解释器启动 text/structured Demo，并检查 UTF-8 输出、轨迹和指标。第四阶段手工复验：

- text：成功，4条消息，MessagePack 0；
- structured：成功，9条协议消息，3次/384 B SemanticState。

## 7. Benchmark 测试

覆盖配置矩阵、实验选择、数据库/状态目录隔离、JSONL、UTF-8-SIG CSV、汇总、环境脱敏、失败记录和冷启动导入。

阶段三正式结果为300/300成功。第四阶段额外在系统临时目录执行1轮五配置最小验证，共30/30成功，结束后目录自动清理，未覆盖正式结果。

## 8. 消融开关

- 无记忆：查询、命中和 SQLite 增长为0；
- 无 SemanticState：传递和状态文件为0；
- 无 result_ref：引用为0，完整结果传输大于0且序列化字节增加；
- text：协议消息和 MessagePack 为0。

## 9. 稳定性

阶段三完整 structured 连续60个任务全部成功，无异常和重试；数据库句柄释放、临时目录清理成功。

## 10. Streamlit

4项 UI 测试验证真实编排、Agent 卡片、记忆、状态元数据、Reviewer 字段、Benchmark 缺失处理和页面 Fake 任务。

实际服务验证：

- `python -m streamlit run app/ui/streamlit_app.py` 由固定脚本启动；
- `/_stcore/health` 返回200；
- 验证后8501监听和项目 Streamlit 进程为0。

## 11. Windows 最终结果

```text
77 passed, 1 warning, 0 failed, 0 errors
```

`pip check`：

```text
No broken requirements found.
```

## 12. openEuler 结果

已在 openEuler 24.03-LTS-SP3 x86_64 实机完成验证：

```text
Python 3.11.6
pip check: No broken requirements found.
pytest: 77 passed, 1 warning, 0 failed, 0 errors
```

使用的解释器为 `/home/fjy/memlink/.venv/bin/python`。该结果是 Linux 实机执行
结果，不是从 Windows 静态检查推断。

## 13. 真实 DeepSeek structured 演示

Windows 和 openEuler 均已完成人工 DeepSeek 入口验证。已记录的一次 structured
成功结果如下：

| 项目 | 真实结果 |
| --- | --- |
| 后端 / 模型 | `deepseek` / `deepseek-v4-pro` |
| Agent 轨迹 | planner → retriever → executor → reviewer |
| 消息数量 / 估算 Token | 9 / 1040 |
| JSON / MessagePack | 7734 B / 7002 B |
| SemanticState | 3次，共384 B |
| 共享记忆命中 | 15 |
| 总耗时 | 28107.309 ms |
| 任务状态 | 成功完成 |
| 密钥显示 | 仅“API Key 已配置”，未显示密钥 |

约28秒包括外部网络和真实模型推理耗时。这是单次功能演示，不是多轮性能
Benchmark，不能用来声称 structured 在所有任务中都比 text 更快。

## 14. warning

唯一 warning：

```text
StarletteDeprecationWarning:
Using httpx with starlette.testclient is deprecated; install httpx2 instead.
```

根据项目约束未安装 `httpx2`，也未大范围升级 FastAPI、Starlette、pytest 或
httpx。warning 不影响当前77项测试。

## 15. 验证边界与已知问题

- 项目中存在本轮开始前已有的 Windows `.venv`，本阶段未使用、创建或删除；
- Streamlit 是比赛演示界面，不含认证和多人隔离；
- structured 在 Fake Benchmark 中部分性能指标差于 text；
- DeepSeek 单次结果受网络、服务负载和模型推理影响，不能替代300条 Fake
  Benchmark；
- 自动测试、Fake Benchmark 与真实 DeepSeek 演示是三套不同验证条件。

## 16. 安全与产物

- API Key 只从被 Git 忽略的根目录 `.env` 读取；
- 测试使用 Fake 或 MockTransport，不读取用户凭据、不访问真实 API；
- 不提交 `.env`、SQLite 数据库、`.npy` 状态、原始密钥或包含密钥的日志；
- 不建议使用真实 DeepSeek 运行300条正式 Benchmark。

## 17. 复现命令

```powershell
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m pip check
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m pytest -q
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m app.cli run-demo --mode text
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m app.cli run-demo --mode structured
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m app.benchmark.cli run --rounds 1
D:\Users\fjy\AppData\Local\anaconda3\envs\memlink\python.exe -m streamlit run app/ui/streamlit_app.py
```

最小 Benchmark 如需保留阶段三正式结果，应使用独立 `--results-dir`。
