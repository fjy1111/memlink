"""Deterministic offline LLM used by development, tests, and demonstrations."""

from app.core.logging import get_logger
from app.models.domain import AgentRole, Task

logger = get_logger(__name__)


class FakeLLM:
    """Generate role-specific text without network access or an API key."""

    async def generate(
        self,
        role: AgentRole,
        task: Task,
        input_text: str,
    ) -> str:
        """Return deterministic Chinese output for the requested agent role."""

        logger.debug("FakeLLM generating %s output for %s", role.value, task.task_id)
        if role is AgentRole.PLANNER:
            return (
                f"任务：{task.title}\n"
                f"原始问题：{task.prompt}\n\n"
                "排查计划：\n"
                "1. 明确故障时间窗、影响范围和服务级别指标。\n"
                "2. 对比应用、依赖服务、数据库与基础设施监控。\n"
                "3. 按变更、容量、错误和延迟四类假设收集证据。\n"
                "4. 先止损，再验证根因，最后给出复盘与预防措施。"
            )
        if role is AgentRole.RETRIEVER:
            return (
                f"任务：{task.title}\n"
                f"原始问题：{task.prompt}\n\n"
                f"收到的完整规划：\n{input_text}\n\n"
                "检索到的故障分析知识：\n"
                "- 使用请求量、错误率、延迟和资源饱和度四个黄金信号。\n"
                "- 检查最近发布、配置变更、依赖超时与数据库连接池。\n"
                "- 用 trace_id 串联入口、业务逻辑、缓存、数据库和下游服务。\n"
                "- 回滚或限流属于止损动作，必须保留监控对照来验证效果。"
            )
        if role is AgentRole.EXECUTOR:
            return (
                f"任务：{task.title}\n"
                f"原始问题：{task.prompt}\n\n"
                f"收到的完整检索上下文：\n{input_text}\n\n"
                "执行结论：\n"
                "1. 先冻结非必要发布并保存故障时间窗内的日志、指标和追踪数据。\n"
                "2. 按接口与实例切分 P95 延迟和 5xx，定位异常集中点。\n"
                "3. 对照变更记录，检查连接池等待、线程/协程堆积和下游超时。\n"
                "4. 若用户影响持续，执行可回滚的限流、扩容或版本回退。\n"
                "5. 通过错误率与延迟恢复情况验证止损，并用最小实验确认根因。"
            )
        if role is AgentRole.REVIEWER:
            return (
                f"企业技术故障分析最终报告：{task.title}\n\n"
                "建议按“保护证据—缩小范围—止损—验证根因—复盘”推进。"
                "立即保留故障窗口的日志、指标、调用链和变更记录；"
                "以请求量、错误率、P95 延迟、资源饱和度为主线，"
                "重点核查近期发布、依赖超时、数据库连接池及任务堆积。"
                "若影响仍在扩大，应优先采用可回滚的限流、扩容或回退措施，"
                "并通过前后监控对照确认恢复。最终根因只有在日志、指标或"
                "最小复现实验相互印证后才能定论。\n\n"
                f"审查所依据的完整执行上下文：\n{input_text}"
            )
        raise ValueError(f"Unsupported agent role: {role}")
