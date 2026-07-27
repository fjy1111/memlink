# openEuler 24.03-LTS-SP3 部署与验证

> 状态：**待 openEuler 实机验证**。本文和脚本已在 Windows 做静态路径、LF 和内容检查，但没有虚构实机通过结论。Windows 静态检查不能替代实机验证。

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

需要记录真实通过数量、warning 和失败日志，不能直接沿用 Windows 结果。

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

密钥只通过当前 shell 环境变量提供。默认验收不要消耗真实模型余额：

```bash
.venv/bin/python -m app.benchmark.cli run \
  --rounds 3 \
  --experiment all \
  --backend openai_compatible
```

配置不完整时入口会明确跳过。密钥不会保存到页面、日志或结果文件。

## 18. 常见问题

- venv 失败：确认 Python 发行包包含 `venv`/`ensurepip`；
- NumPy/PyArrow 安装失败：确认 x86_64、Python 版本和 wheel 可用，必要时安装编译工具；
- 中文乱码：确认 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 和 UTF-8 locale；
- SQLite 只读：检查仓库所有者、目录权限和挂载选项；
- 端口占用：使用 `ss -ltnp` 定位，只处理本项目进程；
- Benchmark 失败：保留原始 JSONL 和完整终端日志，不修改失败记录。

## 19. 实测记录填写

实机完成后请填写：

- openEuler 完整版本：待填写；
- Python 版本：待填写；
- `pip check`：待填写；
- pytest 数量和 warning：待填写；
- text/structured Demo：待填写；
- API/Streamlit：待填写；
- Benchmark 记录数与失败数：待填写；
- 端口和进程清理：待填写；
- 日志或截图路径：待填写。
