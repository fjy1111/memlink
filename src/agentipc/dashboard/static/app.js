"use strict";

let runIndex = [];
let currentRun = null;
let currentTraceBundle = null;
let selectedTrace = null;

const comparisonMetrics = [
  ["success_rate", "Success rate", "percent"],
  ["message_count", "Message count", "mean"],
  ["text_chars", "Text chars", "mean"],
  ["text_tokens", "Text tokens", "mean"],
  ["protocol_bytes", "Protocol bytes", "mean"],
  ["latency_ms", "Latency (ms)", "mean"],
  ["state_transfer_count", "State transfers", "mean"],
  ["state_bytes", "State bytes", "mean"],
  ["memory_retrieved", "Memory retrieved", "mean"],
  ["memory_used", "Memory used", "mean"],
  ["memory_effective", "Memory effective", "mean"],
  ["memory_harmful", "Memory harmful", "mean"],
  ["tool_call_count", "Tool calls", "mean"],
  ["llm_call_count", "LLM calls", "mean"],
  ["llm_prompt_tokens", "LLM prompt tokens", "mean"],
  ["llm_completion_tokens", "LLM completion tokens", "mean"],
  ["llm_total_tokens", "LLM total tokens", "mean"],
  ["llm_latency_ms", "LLM latency (ms)", "mean"],
];

const derivedFields = [
  ["token_saving_rate", "Token saving"],
  ["char_saving_rate", "Char saving"],
  ["latency_improvement_rate", "Latency improvement"],
  ["repeat_work_reduction_rate", "Repeat-work reduction"],
  ["effective_hit_rate", "Effective hit rate"],
];

const el = (id) => document.getElementById(id);

function textNode(tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function safeValue(value) {
  return value === null || value === undefined || Number.isNaN(value) ? "N/A" : String(value);
}

function formatMean(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "N/A";
}

function formatPercent(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "N/A";
}

function setStatus(message, kind) {
  const node = el("page-status");
  node.textContent = message;
  node.className = "status-pill";
  if (kind) node.classList.add(kind);
}

function setEmpty(container, message) {
  container.replaceChildren(textNode("p", message, "empty-state"));
}

function addMeta(container, label, value, metric = false) {
  const wrapper = document.createElement("div");
  wrapper.className = metric ? "metric-item" : "meta-item";
  wrapper.append(textNode("span", label, metric ? "metric-label" : "meta-label"));
  wrapper.append(textNode("span", safeValue(value), metric ? "metric-value" : "meta-value"));
  container.append(wrapper);
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadRuns() {
  try {
    const payload = await fetchJson("/api/runs");
    runIndex = Array.isArray(payload.runs) ? payload.runs : [];
    renderRunIndex();

    const ready = runIndex.filter((run) => run.status === "ready");
    if (!ready.length) {
      clearDashboard("No ready benchmark results found.");
      setStatus("No ready benchmark runs", "error");
      return;
    }

    setStatus("Dashboard ready", "ok");
    await selectRun(ready[0].run_id);
  } catch (error) {
    showLoadError();
  }
}

function renderRunIndex() {
  const counts = { ready: 0, incomplete: 0, invalid: 0 };
  for (const run of runIndex) {
    if (Object.prototype.hasOwnProperty.call(counts, run.status)) counts[run.status] += 1;
  }
  el("run-counts").textContent = `${counts.ready} ready · ${counts.incomplete} incomplete · ${counts.invalid} invalid`;

  const select = el("run-select");
  select.replaceChildren();
  const ready = runIndex.filter((run) => run.status === "ready");
  for (const run of ready) {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = run.run_id;
    select.append(option);
  }
  select.disabled = ready.length === 0;
}

async function selectRun(runId) {
  const select = el("run-select");
  select.value = runId;
  try {
    const [detail, traces] = await Promise.all([
      fetchJson(`/api/runs/${encodeURIComponent(runId)}`),
      fetchJson(`/api/runs/${encodeURIComponent(runId)}/traces`),
    ]);
    currentRun = detail;
    currentTraceBundle = traces;
    renderRunSummary();
    renderComparison();
    renderDerived();
    renderEnvironment();
    renderTraceSelector();
  } catch (error) {
    showLoadError();
  }
}

function renderRunSummary() {
  const container = el("run-meta");
  container.replaceChildren();
  if (!currentRun) {
    setEmpty(container, "No ready benchmark results found.");
    return;
  }
  const indexEntry = runIndex.find((run) => run.run_id === currentRun.run_id) || {};
  addMeta(container, "Run ID", currentRun.run_id);
  addMeta(container, "Status", indexEntry.status || "ready");
  addMeta(container, "LLM provider", currentRun.environment?.llm_provider);
  addMeta(container, "Embedding", currentRun.environment?.embedding_provider);
  addMeta(container, "Records", currentRun.summary?.total_records);
  addMeta(container, "Tasks", currentRun.summary?.task_count);
  addMeta(container, "Seeds", currentRun.summary?.seed_count);
  addMeta(container, "Report", currentRun.report?.title || indexEntry.report_title);
}

function renderComparison() {
  const body = el("comparison-body");
  body.replaceChildren();
  const experiments = currentRun?.summary?.experiments;
  if (!experiments) {
    appendTableMessage(body, 5, "No A/B/C/D comparison data available.");
    return;
  }

  for (const [metricName, label, kind] of comparisonMetrics) {
    const row = document.createElement("tr");
    const header = textNode("th", label);
    header.scope = "row";
    row.append(header);
    for (const experimentName of ["A", "B", "C", "D"]) {
      const experiment = experiments[experimentName];
      let value;
      if (kind === "percent") {
        value = formatPercent(experiment?.success_rate);
      } else {
        value = formatMean(experiment?.metrics?.[metricName]?.mean);
      }
      row.append(textNode("td", value));
    }
    body.append(row);
  }
}

function renderDerived() {
  const body = el("derived-body");
  body.replaceChildren();
  if (!currentRun?.derived) {
    appendTableMessage(body, 6, "No derived comparison data available.");
    return;
  }

  for (const [key, label] of [["B_vs_A", "B vs A"], ["C_vs_B", "C vs B"], ["D_vs_C", "D vs C"]]) {
    const row = document.createElement("tr");
    const header = textNode("th", label);
    header.scope = "row";
    row.append(header);
    const values = currentRun.derived[key] || {};
    for (const [field] of derivedFields) row.append(textNode("td", formatPercent(values[field])));
    body.append(row);
  }
}

function appendTableMessage(body, colspan, message) {
  const row = document.createElement("tr");
  const cell = textNode("td", message);
  cell.colSpan = colspan;
  cell.className = "muted";
  row.append(cell);
  body.append(row);
}

function renderTraceSelector() {
  const select = el("trace-select");
  select.replaceChildren();
  const traces = Array.isArray(currentTraceBundle?.traces) ? currentTraceBundle.traces : [];
  if (!traces.length) {
    const option = textNode("option", "No trace data");
    select.append(option);
    select.disabled = true;
    selectedTrace = null;
    renderSelectedTrace();
    return;
  }

  traces.forEach((trace, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${safeValue(trace.experiment)} · seed ${safeValue(trace.seed)} · ${safeValue(trace.task_id)}`;
    select.append(option);
  });
  select.disabled = false;
  const preferred = traces.findIndex((trace) => trace.experiment === "D");
  const selectedIndex = preferred >= 0 ? preferred : 0;
  select.value = String(selectedIndex);
  selectedTrace = traces[selectedIndex];
  renderSelectedTrace();
}

function renderSelectedTrace() {
  renderTimeline();
  renderState();
  renderMemory();
}

function renderTimeline() {
  const container = el("timeline");
  container.replaceChildren();
  const status = el("trace-status");
  if (!selectedTrace) {
    status.textContent = "No task trace selected.";
    setEmpty(container, "Trace data unavailable for this task.");
    return;
  }

  status.textContent = `${safeValue(selectedTrace.experiment)} · seed ${safeValue(selectedTrace.seed)} · ${safeValue(selectedTrace.trace_status)}`;
  if (selectedTrace.trace_status !== "ready" || !Array.isArray(selectedTrace.events)) {
    setEmpty(container, "Trace data unavailable for this task.");
    return;
  }

  const workflow = selectedTrace.events.filter((event) => event.action !== null && event.action !== undefined);
  if (!workflow.length) {
    setEmpty(container, "Trace data unavailable for this task.");
    return;
  }

  for (const event of workflow) {
    const item = document.createElement("li");
    item.className = "timeline-item";
    item.append(textNode("span", safeValue(event.sender), "timeline-node"));
    item.append(textNode("span", `→ ${safeValue(event.action)} →`, "timeline-action"));
    item.append(textNode("span", safeValue(event.receiver), "timeline-node"));
    item.append(textNode("span", `${safeValue(event.status)} · ${safeValue(event.step_id)}`, "timeline-tail"));
    container.append(item);
  }
}

function renderState() {
  const container = el("state-list");
  container.replaceChildren();
  if (!selectedTrace || selectedTrace.trace_status !== "ready") {
    setEmpty(container, "No non-text state references in this task.");
    return;
  }

  const unique = new Map();
  for (const event of selectedTrace.events || []) {
    for (const ref of event.state_refs || []) {
      const key = `${safeValue(ref.transport)}|${safeValue(ref.uri)}|${safeValue(ref.checksum)}`;
      if (!unique.has(key)) unique.set(key, ref);
    }
  }

  if (!unique.size) {
    setEmpty(container, "No non-text state references in this task.");
    return;
  }

  for (const ref of unique.values()) {
    const card = document.createElement("article");
    card.className = "evidence-card";
    card.append(textNode("h3", safeValue(ref.kind), "evidence-title"));
    const grid = document.createElement("div");
    grid.className = "evidence-grid";
    addEvidence(grid, "Transport", ref.transport);
    addEvidence(grid, "Shape", Array.isArray(ref.shape) ? `[${ref.shape.join(", ")}]` : "N/A");
    addEvidence(grid, "dtype", ref.dtype);
    addEvidence(grid, "Bytes", ref.nbytes);
    addEvidence(grid, "Summary", ref.summary);
    card.append(grid);
    container.append(card);
  }
}

function renderMemory() {
  const metricsContainer = el("memory-metrics");
  const list = el("memory-list");
  metricsContainer.replaceChildren();
  list.replaceChildren();

  const metrics = selectedTrace?.metrics || {};
  for (const [label, key] of [["Retrieved", "memory_retrieved"], ["Used", "memory_used"], ["Effective", "memory_effective"], ["Harmful", "memory_harmful"]]) {
    addMeta(metricsContainer, label, metrics[key] ?? "N/A", true);
  }

  if (!selectedTrace || selectedTrace.trace_status !== "ready") {
    setEmpty(list, "No memory reference was reused in this task.");
    return;
  }

  const unique = new Map();
  for (const event of selectedTrace.events || []) {
    for (const ref of event.memory_refs || []) {
      const key = `${safeValue(ref.memory_id)}|${safeValue(ref.match_type)}|${safeValue(ref.score)}`;
      if (!unique.has(key)) unique.set(key, ref);
    }
  }

  if (!unique.size) {
    setEmpty(list, "No memory reference was reused in this task.");
    return;
  }

  for (const ref of unique.values()) {
    const card = document.createElement("article");
    card.className = "evidence-card";
    card.append(textNode("h3", safeValue(ref.memory_id), "evidence-title"));
    const grid = document.createElement("div");
    grid.className = "evidence-grid";
    addEvidence(grid, "Match type", ref.match_type);
    addEvidence(grid, "Score", ref.score);
    addEvidence(grid, "Summary", ref.summary);
    card.append(grid);
    list.append(card);
  }
}

function addEvidence(container, key, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "evidence-row";
  wrapper.append(textNode("span", key, "evidence-key"));
  wrapper.append(textNode("span", safeValue(value), "evidence-value"));
  container.append(wrapper);
}

function renderEnvironment() {
  const container = el("environment");
  container.replaceChildren();
  const environment = currentRun?.environment;
  if (!environment) {
    setEmpty(container, "Environment data unavailable.");
    return;
  }
  for (const [label, key] of [["OS", "os_name"], ["Platform", "platform"], ["Python", "python_version"], ["LLM provider", "llm_provider"], ["Embedding provider", "embedding_provider"], ["Token method", "token_method"]]) {
    const wrapper = document.createElement("div");
    wrapper.append(textNode("dt", label));
    wrapper.append(textNode("dd", safeValue(environment[key])));
    container.append(wrapper);
  }
}

function clearDashboard(message) {
  currentRun = null;
  currentTraceBundle = null;
  selectedTrace = null;
  const meta = el("run-meta");
  meta.replaceChildren();
  setEmpty(meta, message);
  const comparison = el("comparison-body");
  comparison.replaceChildren();
  appendTableMessage(comparison, 5, message);
  const derived = el("derived-body");
  derived.replaceChildren();
  appendTableMessage(derived, 6, message);
  renderTraceSelector();
  renderEnvironment();
}

function showLoadError() {
  setStatus("Unable to load dashboard data", "error");
  el("run-counts").textContent = "Unable to load AgentIPC dashboard data.";
  clearDashboard("Unable to load AgentIPC dashboard data.");
}

el("run-select").addEventListener("change", (event) => {
  void selectRun(event.target.value);
});

el("trace-select").addEventListener("change", (event) => {
  const traces = Array.isArray(currentTraceBundle?.traces) ? currentTraceBundle.traces : [];
  const index = Number.parseInt(event.target.value, 10);
  selectedTrace = Number.isInteger(index) ? traces[index] || null : null;
  renderSelectedTrace();
});

void loadRuns();
