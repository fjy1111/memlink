# openEuler 24.03-LTS-SP3 部署与验证

> 状态：**已完成 openEuler 实机验证**。验证环境为 openEuler
> 24.03-LTS-SP3 x86_64、Python 3.11.6，解释器为
> `/home/fjy/memlink/.venv/bin/python`。

## 1. 目标与硬件建议

- 系统：openEuler 24.03-LTS-SP3 x86_64；
- Python：3.11 或更高；
- 建议：2 CPU、4 GiB 内存、5 GiB 可用磁盘；
- 默认 Fake 模式不需要 GPU、外网或 API Key。

## 2. 获取代码

```bash
git clone <比赛仓库地址> memlink
cd memlink
```

仓库地址需由维护者在正式发布后替换。

## 3. 系统和 Python 检查

```bash
cat /etc/openEuler-release
uname -m
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
```

如缺少 Python、Git 或编译工具，请使用实际 openEuler 软件源安装对应包；不同镜像的包名可能不同，应以实机仓库为准。

## 4. 自动安装

```bash
bash scripts/linux/setup.sh
```

脚本会读取 `/etc/os-release`、创建仓库内 `.venv`、安装 `requirements-dev.txt`、创建运行目录、设置当前用户权限、设置脚本执行权限并运行 `pip check`。

## 5. 手工等价步骤

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
mkdir -p data/metrics data/states data/memory benchmarks/results
chmod u+rwX data/metrics data/states data/memory benchmarks/results
python -m pip check
```

不要复制 Windows Conda 环境到 openEuler。

## 6. pytest

```bash
bash scripts/linux/test.sh
```

等价命令：

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

实机记录：

```text
pip check: No broken requirements found.
pytest: 77 passed, 1 warning, 0 failed, 0 errors
```

以上为 openEuler 实际执行结果，不是沿用 Windows 输出。

## 7. CLI Demo

```bash
bash scripts/linux/run_demo.sh
```

脚本依次运行 text 和 structured。默认设置 `MEMLINK_LLM_BACKEND=fake` 和 `MEMLINK_EMBEDDING_BACKEND=fake`。

## 8. Uvicorn API

```bash
bash scripts/linux/start.sh
```

默认监听 `0.0.0.0:8000`。另开终端验证：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/api/v1/tasks/run \
  -H 'Content-Type: application/json' \
  -d '{"title":"openEuler API 故障分析","prompt":"生产 API 频繁返回 500，请给出排查方案。","mode":"text"}'
```

从 POST 返回中复制真实 `task_id`：

```bash
curl -fsS http://127.0.0.1:8000/api/v1/tasks/<task_id>
```

## 9. Streamlit

```bash
bash scripts/linux/start_ui.sh
```

默认监听 `0.0.0.0:8501`。浏览器访问 `http://<虚拟机地址>:8501`。页面不接收 API Key；Fake 模式可以离线演示。

## 10. Benchmark

```bash
bash scripts/linux/collect_environment.sh
bash scripts/linux/run_benchmark.sh 10
```

这会执行五种配置、两组任务、每种配置10轮，并输出300条任务记录。结果保存在 `benchmarks/results/`，正式提交前需人工检查。

仓库现有正式300条结果来自 Fake 后端可复现实验。openEuler 的依赖、pytest 和
真实模型入口已实机验证，但不能据此声称又在 openEuler 重跑了300条记录。若需要
生成 openEuler 专属 Benchmark，必须实际执行上述命令并保留新的环境与原始结果。

## 11. 防火墙

仅在需要从宿主机访问虚拟机且安全策略允许时开放端口：

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --permanent --add-port=8501/tcp
sudo firewall-cmd --reload
```

比赛演示结束后应按组织策略关闭不需要的端口。

## 12. 文件与 SQLite 权限

```bash
chmod -R u+rwX data benchmarks/results
test -w data/memory
test -w data/states
```

SQLite 文件和 `-wal`/`-shm` 文件必须由运行用户读写。不要用 root 启动一次、普通用户再继续写同一数据库。

## 13. SemanticState 权限

StateStore 需要在 `data/states` 创建 `.npy`、`.json` 和临时文件。目录不可写时任务会明确失败，不应捕获后伪造成功。

## 14. 日志和结果位置

- Uvicorn/Streamlit：前台终端标准输出；
- 单任务指标：`data/metrics/*.json`；
- 状态：`data/states/`；
- 共享记忆：`data/memory/memlink.db`；
- Benchmark：`benchmarks/results/`。

## 15. 停止服务

在对应前台终端按 `Ctrl+C`，随后检查：

```bash
ss -ltnp | grep -E ':(8000|8501)' || true
pgrep -af 'uvicorn|streamlit|pytest|app.benchmark' || true
```

只能处理命令行明确指向当前 MemLink 仓库的进程。

## 16. 清理运行数据

先停止服务并列出目标：

```bash
find data/metrics data/states data/memory -maxdepth 1 -type f -print
```

确认只包含可再生运行数据后，可执行：

```bash
find data/metrics -maxdepth 1 -type f -name '*.json' -delete
find data/states -maxdepth 1 -type f \( -name '*.npy' -o -name '*.json' \) -delete
find data/memory -maxdepth 1 -type f -name 'memlink.db*' -delete
```

不要删除 `.gitkeep`、源码或未备份的正式实验结果。

## 17. 真实模型（可选）

DeepSeek 密钥只写入 `/home/fjy/memlink/.env`，不得写入 shell 历史、源码或
页面。默认验收和 Benchmark 不消耗真实模型余额。完成 `.env` 配置后，可人工
运行两种通信模式：

```bash
cd /home/fjy/memlink
.venv/bin/python -m app.cli run-demo --mode text --backend deepseek
.venv/bin/python -m app.cli run-demo --mode structured --backend deepseek
```

配置不完整或请求失败时入口会返回脱敏错误，不会回退到 Fake。密钥不会保存到
页面、日志、结果文件或 Benchmark。

已完成的一次真实 structured 演示记录：

```text
backend: deepseek
model: deepseek-v4-pro
trace: planner -> retriever -> executor -> reviewer
message_count: 9
estimated_tokens: 1040
json_bytes: 7734
messagepack_bytes: 7002
semantic_state: 3 次，共 384 B
shared_memory_hits: 15
total_duration_ms: 28107.309
status: completed
api_key_display: 已配置
```

约28秒属于外部网络和模型推理参与的单次演示耗时，不应与 Fake Benchmark 的
毫秒级耗时直接比较。该结果证明真实模型接入成功，但不能替代多轮 Benchmark。

## 18. 常见问题

- venv 失败：确认 Python 发行包包含 `venv`/`ensurepip`；
- NumPy/PyArrow 安装失败：确认 x86_64、Python 版本和 wheel 可用，必要时安装编译工具；
- 中文乱码：确认 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 和 UTF-8 locale；
- SQLite 只读：检查仓库所有者、目录权限和挂载选项；
- 端口占用：使用 `ss -ltnp` 定位，只处理本项目进程；
- Benchmark 失败：保留原始 JSONL 和完整终端日志，不修改失败记录。

## 19. 实测记录

- openEuler 完整版本：openEuler 24.03-LTS-SP3 x86_64；
- Python 版本：3.11.6；
- 解释器：`/home/fjy/memlink/.venv/bin/python`；
- `pip check`：`No broken requirements found.`；
- pytest：77 passed，1 warning，0 failed，0 errors；
- DeepSeek structured：`deepseek-v4-pro`，四 Agent 顺序执行并成功完成；
- DeepSeek 单次耗时：28107.309 ms；
- API Key：输出中仅显示“已配置”，未出现原始密钥；
- 正式 Benchmark：现有300条为 Fake 后端可复现实验，不冒充 openEuler
  DeepSeek Benchmark；
- 未由本次记录覆盖的 API、Streamlit、端口清理或截图，应以各自真实日志为准。
