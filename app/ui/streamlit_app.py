"""Competition demo page for MemLink's real orchestration services."""

from typing import Any

import streamlit as st

from app.core.config import get_settings
from app.agents.base import AgentExecutionError
from app.llm import LLMClientError
from app.models import CommunicationMode, TaskResult
from app.runtime.orchestrator import OrchestrationError, TaskOrchestrator
from app.ui.presenter import (
    benchmark_table_rows,
    build_benchmark_chart,
    build_agent_cards,
    build_memory_rows,
    build_semantic_state_rows,
)
from app.ui.service import (
    build_orchestrator,
    deepseek_backend_is_configured,
    load_benchmark_results,
    load_examples,
    run_coroutine,
    run_task,
)

st.set_page_config(
    page_title="MemLink 演示系统",
    page_icon="🔗",
    layout="wide",
)


def render_overview() -> None:
    """Render the project identity and implemented mechanisms."""

    st.title("MemLink")
    st.caption("面向多智能体协作的低开销通信、状态传递与共享记忆机制")
    columns = st.columns(4)
    for column, title, body in zip(
        columns,
        ("四个 Agent", "双通信模式", "非文本状态", "共享记忆与评测"),
        (
            "Planner → Retriever → Executor → Reviewer",
            "text 基线 / structured 协议",
            "NumPy SemanticState + state_id",
            "SQLite 跨任务复用 + 可消融 Benchmark",
        ),
        strict=True,
    ):
        with column:
            st.subheader(title)
            st.write(body)


def get_demo_orchestrator(
    *,
    backend: str,
    enable_shared_memory: bool,
    enable_semantic_state: bool,
    enable_result_reference: bool,
) -> TaskOrchestrator:
    """Reuse one orchestrator per page configuration to demonstrate memory."""

    key = (
        backend,
        enable_shared_memory,
        enable_semantic_state,
        enable_result_reference,
    )
    if st.session_state.get("orchestrator_key") != key:
        st.session_state["orchestrator"] = build_orchestrator(
            get_settings(),
            backend=backend,
            enable_shared_memory=enable_shared_memory,
            enable_semantic_state=enable_semantic_state,
            enable_result_reference=enable_result_reference,
        )
        st.session_state["orchestrator_key"] = key
    return st.session_state["orchestrator"]


def render_agent_trace(
    result: TaskResult,
    orchestrator: TaskOrchestrator,
) -> None:
    """Render four role-specific steps from the actual task result."""

    st.subheader("Agent 执行轨迹")
    for card in build_agent_cards(result, orchestrator):
        with st.expander(
            f"{card['agent']} · {card['action']} · "
            f"{card['duration_ms']:.3f} ms",
            expanded=True,
        ):
            st.write("Capability：", ", ".join(card["capabilities"]))
            st.write("状态：", card["status"])
            st.write("输入摘要：", card["input_summary"])
            st.write("输出摘要：", card["output_summary"])
            st.write(
                "证据引用：",
                ", ".join(card["evidence_ids"]) or "无",
            )


def render_communication_metrics(result: TaskResult) -> None:
    """Render measured communication and timing values."""

    st.subheader("通信指标")
    metrics = result.metrics
    values = (
        ("文本字符", metrics.text_character_count),
        ("估算 Token", metrics.estimated_token_count),
        ("协议消息", metrics.protocol_message_count),
        ("JSON 字节", metrics.json_serialized_bytes),
        ("MessagePack 字节", metrics.msgpack_serialized_bytes),
        (
            "SemanticState",
            f"{metrics.semantic_state_transfer_count} 次 / "
            f"{metrics.semantic_state_bytes} B",
        ),
        ("result_ref", metrics.result_reference_count),
        ("总耗时", f"{metrics.total_duration_ms:.3f} ms"),
    )
    columns = st.columns(4)
    for index, (label, value) in enumerate(values):
        columns[index % 4].metric(label, value)


def render_memory_and_state(
    result: TaskResult,
    orchestrator: TaskOrchestrator,
) -> None:
    """Render safe memory and semantic-state metadata."""

    memory_tab, state_tab = st.tabs(["共享记忆", "SemanticState"])
    with memory_tab:
        st.metric("memory_hit_count", result.memory_hit_count)
        st.write(
            "reused_memory_ids：",
            ", ".join(result.reused_memory_ids) or "无",
        )
        memory_rows = build_memory_rows(result, orchestrator)
        if memory_rows:
            st.dataframe(memory_rows, use_container_width=True)
        else:
            st.info("当前任务没有复用既有共享记忆；可连续运行同组任务观察命中。")
    with state_tab:
        state_rows = build_semantic_state_rows(result, orchestrator)
        if state_rows:
            st.dataframe(state_rows, use_container_width=True)
            st.caption("页面只展示元数据，不读取或打印完整向量。")
        else:
            st.info("当前模式未传递 SemanticState。")


def render_final_result(result: TaskResult) -> None:
    """Render Reviewer facts returned by the orchestration layer."""

    st.subheader("最终结果")
    if result.review_passed is None:
        st.info("text 基线返回 Reviewer 的完整文本交接，不生成结构化审查字段。")
    else:
        st.write("审查状态：", "通过" if result.review_passed else "未通过")
        st.write("置信度：", f"{result.review_confidence:.2f}")
    st.write("证据链：", ", ".join(result.evidence_ids) or "无结构化证据 ID")
    st.write("contradiction：", result.contradictions or "无")
    st.write("missing_evidence：", result.missing_evidence or "无")
    st.write("recommendations：", result.recommendations or "无")
    st.success(result.final_answer)


def render_task_demo() -> None:
    """Render inputs and execute the real TaskOrchestrator on demand."""

    settings = get_settings()
    examples = load_examples()
    labels = ["自定义任务", *(example["label"] for example in examples)]
    selected_label = st.selectbox("示例任务", labels)
    selected = next(
        (
            example
            for example in examples
            if example["label"] == selected_label
        ),
        None,
    )
    title = st.text_input(
        "任务标题",
        value=selected["title"] if selected else "企业技术故障分析",
    )
    prompt = st.text_area(
        "任务描述",
        value=(
            selected["prompt"]
            if selected
            else "生产 API 延迟升高并出现少量 HTTP 500，请给出排查方案。"
        ),
        height=130,
    )
    task_topic = st.text_input(
        "任务主题",
        value=selected["task_topic"] if selected else "enterprise-incident",
    )
    mode = CommunicationMode(
        st.radio(
            "通信模式",
            options=[mode.value for mode in CommunicationMode],
            horizontal=True,
        )
    )

    backend_options = {
        "Fake（离线演示）": "fake",
        "DeepSeek（真实模型）": "deepseek",
    }
    backend_label = st.selectbox("模型后端", list(backend_options))
    selected_backend = backend_options[backend_label]
    if selected_backend == "deepseek":
        key_is_configured = (
            bool(settings.deepseek_api_key.strip())
            and settings.deepseek_api_key.strip() != "replace-me"
        )
        key_status = (
            "已配置"
            if key_is_configured
            else "未配置"
        )
        st.write("当前后端：DeepSeek")
        st.write(f"模型名称：{settings.deepseek_model or '未配置'}")
        st.write(f"Base URL：{settings.deepseek_base_url or '未配置'}")
        st.write(f"API Key：{key_status}")
        if not deepseek_backend_is_configured(settings):
            st.warning("DeepSeek 配置不完整，运行前请更新项目根目录的 .env。")
    else:
        st.caption("当前后端：Fake；离线运行，不访问互联网。")

    option_columns = st.columns(3)
    enable_shared_memory = option_columns[0].toggle(
        "共享记忆",
        value=True,
    )
    enable_semantic_state = option_columns[1].toggle(
        "SemanticState",
        value=mode is CommunicationMode.STRUCTURED,
    )
    enable_result_reference = option_columns[2].toggle(
        "result_ref",
        value=mode is CommunicationMode.STRUCTURED,
    )

    if st.button("运行四 Agent 协作", type="primary"):
        try:
            orchestrator = get_demo_orchestrator(
                backend=selected_backend,
                enable_shared_memory=enable_shared_memory,
                enable_semantic_state=enable_semantic_state,
                enable_result_reference=enable_result_reference,
            )
            with st.spinner("Planner、Retriever、Executor、Reviewer 正在协作…"):
                result = run_coroutine(
                    run_task(
                        orchestrator,
                        title=title,
                        prompt=prompt,
                        task_topic=task_topic,
                        mode=mode,
                    )
                )
            st.session_state["last_result"] = result
            st.session_state["last_orchestrator"] = orchestrator
        except (
            AgentExecutionError,
            LLMClientError,
            OrchestrationError,
            ValueError,
        ) as exc:
            st.error(f"任务运行失败：{exc}")
        except Exception:
            st.error("任务运行失败：发生未预期错误，详细信息已隐藏。")

    result = st.session_state.get("last_result")
    orchestrator = st.session_state.get("last_orchestrator")
    if isinstance(result, TaskResult) and isinstance(
        orchestrator,
        TaskOrchestrator,
    ):
        render_agent_trace(result, orchestrator)
        render_communication_metrics(result)
        render_memory_and_state(result, orchestrator)
        render_final_result(result)


def render_benchmark() -> None:
    """Render real stage-three summaries or a clear missing-data notice."""

    st.subheader("阶段三真实 Benchmark")
    payload = load_benchmark_results()
    if payload is None:
        st.warning(
            "未找到 benchmark_summary.json 和 stability_summary.json。"
            "请先运行 `python -m app.benchmark.cli run --rounds 10`。"
        )
        return
    rows = benchmark_table_rows(payload["summary"])
    st.caption(f"数据目录：{payload['results_dir']}")
    st.dataframe(rows, use_container_width=True)
    st.markdown("#### P50 / P95 耗时")
    st.altair_chart(
        build_benchmark_chart(
            rows,
            (("p50_ms", "P50"), ("p95_ms", "P95")),
            y_axis_title="耗时（ms）",
        ),
        use_container_width=True,
    )
    st.markdown("#### 字符与估算 Token")
    st.altair_chart(
        build_benchmark_chart(
            rows,
            (("characters", "字符"), ("tokens", "估算 Token")),
            y_axis_title="均值",
        ),
        use_container_width=True,
    )
    st.markdown("#### JSON / MessagePack 字节")
    st.altair_chart(
        build_benchmark_chart(
            rows,
            (("json_bytes", "JSON"), ("msgpack_bytes", "MessagePack")),
            y_axis_title="序列化字节（B）",
        ),
        use_container_width=True,
    )
    st.markdown("#### 记忆命中率")
    st.altair_chart(
        build_benchmark_chart(
            rows,
            (("memory_hit_rate", "记忆命中率"),),
            y_axis_title="命中率",
            axis_format=".0%",
            tooltip_format=".2%",
        ),
        use_container_width=True,
    )
    stability: dict[str, Any] = payload["stability"]
    st.markdown("#### 连续稳定性")
    stability_columns = st.columns(4)
    stability_columns[0].metric("连续任务", stability["total_tasks"])
    stability_columns[1].metric(
        "成功 / 失败",
        f"{stability['successful_tasks']} / {stability['failed_tasks']}",
    )
    stability_columns[2].metric(
        "P50 / P95",
        f"{stability['p50_duration_ms']:.3f} / "
        f"{stability['p95_duration_ms']:.3f} ms",
    )
    stability_columns[3].metric(
        "资源清理",
        "成功" if stability["cleanup_success"] else "失败",
    )
    st.info(
        "完整 structured 在本次真实离线结果中字符、估算 Token 和耗时"
        "高于 text；页面按结果如实展示，不预设优化结论。"
    )


render_overview()
task_tab, benchmark_tab = st.tabs(["任务演示", "Benchmark"])
with task_tab:
    render_task_demo()
with benchmark_tab:
    render_benchmark()
