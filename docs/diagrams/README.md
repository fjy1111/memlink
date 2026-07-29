# Mermaid 图导出说明

本目录中的 8 张 `.mmd` 图面向 16:9 比赛 PPT 和项目说明书。源文件使用
UTF-8、中文短标签和统一配色，导出产物统一放在 `docs/diagrams/exports/`。

## 推荐导出

如果系统已经安装 Mermaid CLI：

```powershell
mmdc -i docs/diagrams/memlink_architecture.mmd -o "docs/diagrams/exports/20_MemLink系统架构图.svg" -b white
```

PNG 建议使用白底和 1600×900 画布：

```powershell
mmdc -i docs/diagrams/memlink_architecture.mmd -o "docs/diagrams/exports/20_MemLink系统架构图.png" -b white -w 1600 -H 900 -s 2
```

其余文件按下面的映射导出：

| Mermaid 源文件 | 比赛材料文件名 |
| --- | --- |
| `memlink_architecture.mmd` | `20_MemLink系统架构图` |
| `mode_comparison.mmd` | `21_双通信模式对比图` |
| `multi_agent_sequence.mmd` | `22_多智能体协作时序图` |
| `semantic_state_lifecycle.mmd` | `23_SemanticState生命周期图` |
| `shared_memory_loop.mmd` | `24_共享记忆复用闭环图` |
| `benchmark_design.mmd` | `25_Benchmark实验设计图` |
| `openeuler_deployment.mmd` | `26_openEuler部署拓扑图` |
| `deepseek_security.mmd` | `27_DeepSeek安全接入流程图` |

## 图示用途

| 图 | 简短说明 |
| --- | --- |
| 系统架构图 | 总览入口、编排、Agent、通信状态、模型和评测交付链路。 |
| 双通信模式对比图 | 对照 text 完整文本基线与 structured 结构化机制，并引出上下文增长实验。 |
| 多智能体协作时序图 | 展示一次任务从能力发现到四 Agent 协作、状态/记忆和指标记录的真实顺序。 |
| SemanticState 生命周期图 | 展示 NumPy 状态的生成、二进制保存、`state_id` 引用、按需恢复和清理。 |
| 共享记忆复用闭环图 | 区分检索命中与正确复用，并展示四种记忆证据实验条件。 |
| Benchmark 实验设计图 | 汇总基础 Benchmark、上下文增长和记忆复用实验的规模、隔离目录与指标。 |
| openEuler 部署拓扑图 | 展示从 Windows/Git 到 openEuler 服务、存储和 DeepSeek HTTPS 的部署关系。 |
| DeepSeek 安全接入流程图 | 展示 `.env`、Settings、脱敏日志、Mock 测试和 Fake Benchmark 的安全边界。 |

也可以把 `.mmd` 内容粘贴到 Mermaid Live Editor，优先下载 SVG，再按 PPT
需要转换为白底 PNG。导出后应人工检查中文字体、节点裁切和线条交叉。

## 口径边界

- Fake 是 pytest、基础 Benchmark 和证据实验的默认离线后端。
- DeepSeek 只用于人工真实模型演示，不把离线结果表述成 DeepSeek 性能数据。
- MessagePack 图示表示同一消息集合的编码体积统计，不表示当前运行发生了网络传输。
- `memory_hit_count` 只表示检索命中，不等同于记忆被正确复用。
