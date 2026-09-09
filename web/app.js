const state = {
  scope: "team",
  person: "",
  page: 1,
  pageSize: 20,
  total: 0,
  people: [],
  selected: new Set(),
  singleTarget: null,
  writeEnabled: false,
  wecomEnabled: false,
};

const elements = Object.fromEntries([
  "environment-badge", "sync-time", "person-select", "view-title", "view-description",
  "stat-open", "stat-unassigned", "stat-assigned", "stat-overdue", "stat-due",
  "source-filter", "alert-filter", "search-input", "search-button", "batch-assign-button",
  "export-button", "wecom-send-button", "selection-bar", "selected-count", "success-message", "error-banner",
  "select-all", "task-body", "loading", "empty-state", "result-count", "previous-page",
  "next-page", "page-label", "assign-dialog", "assign-form", "assign-description",
  "assignee-select", "assign-cancel",
].map(id => [id, document.getElementById(id)]));

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function formatDateTime(value) {
  if (!value) return "未设置";
  return String(value).replace("T", " ").slice(0, 16);
}

function formatAmount(value, currency) {
  return `${currency || "CNY"} ${Number(value || 0).toLocaleString("zh-CN", {maximumFractionDigits: 2})}`;
}

function buildQuery(exportMode = false) {
  const params = new URLSearchParams({scope: state.scope, person: state.person});
  if (elements["source-filter"].value) params.set("source", elements["source-filter"].value);
  if (elements["alert-filter"].value) params.set("alert", elements["alert-filter"].value);
  if (elements["search-input"].value.trim()) params.set("search", elements["search-input"].value.trim());
  if (!exportMode) {
    params.set("page", state.page);
    params.set("pageSize", state.pageSize);
  }
  return params.toString();
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok || !body?.success) throw new Error(body?.message || `请求失败：${response.status}`);
  return body.data;
}

function showError(message) {
  elements["error-banner"].textContent = message;
  elements["error-banner"].hidden = false;
}

function clearError() {
  elements["error-banner"].hidden = true;
}

function showSuccess(message) {
  elements["success-message"].textContent = message;
  elements["success-message"].hidden = false;
  window.setTimeout(() => { elements["success-message"].hidden = true; }, 3500);
}

function renderPeople(defaultPerson) {
  const options = state.people.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  elements["person-select"].innerHTML = options;
  elements["assignee-select"].innerHTML = `<option value="">请选择人员</option>${options}`;
  state.person = state.people.includes(defaultPerson) ? defaultPerson : (state.people[0] || "");
  elements["person-select"].value = state.person;
}

function renderTasks(data) {
  const rows = data.items.map(task => {
    const badgeClass = task.alertLevel === "P0" ? "badge-p0" : task.alertLevel === "P1" ? "badge-p1" : task.alertLevel === "P2" ? "badge-p2" : "badge-normal";
    return `<tr data-id="${task.id}">
      <td><input class="row-check" type="checkbox" aria-label="选择${escapeHtml(task.admNo)}" ${state.selected.has(task.id) ? "checked" : ""}></td>
      <td><span class="badge ${badgeClass}">${escapeHtml(task.alertLevel === "NORMAL" ? "正常" : task.alertLevel)} · ${escapeHtml(task.alertText)}</span></td>
      <td class="adm-number">${escapeHtml(task.admNo)}</td>
      <td>${escapeHtml(task.otaCode)}</td>
      <td>${escapeHtml(task.otaOrderNo)}</td>
      <td>${escapeHtml(task.airline)}</td>
      <td>${escapeHtml(formatAmount(task.amount, task.currency))}</td>
      <td>${escapeHtml(formatDateTime(task.deadline))}</td>
      <td>${escapeHtml(task.stageName)}</td>
      <td><span class="owner-cell"><span>${escapeHtml(task.owner || "未分配")}</span><small>实际：${escapeHtml(task.actualOwner || "未分配")}</small></span></td>
      <td><button class="row-action" type="button" ${state.writeEnabled ? `data-transfer="${task.id}"` : "disabled"}>${state.writeEnabled ? "快速转单" : "只读"}</button></td>
    </tr>`;
  }).join("");
  elements["task-body"].innerHTML = rows;
  elements.loading.hidden = true;
  elements["empty-state"].hidden = data.items.length > 0;

  const summary = data.summary;
  elements["stat-open"].textContent = summary.currentOpen.toLocaleString("zh-CN");
  elements["stat-unassigned"].textContent = summary.unassigned.toLocaleString("zh-CN");
  elements["stat-assigned"].textContent = summary.assigned.toLocaleString("zh-CN");
  elements["stat-overdue"].textContent = summary.overdue.toLocaleString("zh-CN");
  elements["stat-due"].textContent = summary.due24h.toLocaleString("zh-CN");
  elements["sync-time"].textContent = `数据更新：${formatDateTime(data.updatedAt)}`;

  state.total = data.pagination.total;
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  elements["result-count"].textContent = `共${state.total.toLocaleString("zh-CN")}条`;
  elements["page-label"].textContent = `第${state.page}页 / 共${totalPages}页`;
  elements["previous-page"].disabled = state.page <= 1;
  elements["next-page"].disabled = state.page >= totalPages;

  const currentSource = elements["source-filter"].value;
  elements["source-filter"].innerHTML = `<option value="">全部数据源</option>${data.sources.map(source => `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`).join("")}`;
  elements["source-filter"].value = data.sources.includes(currentSource) ? currentSource : "";
  elements["select-all"].checked = false;
  updateSelection();
}

async function loadTasks() {
  if (!state.person && state.scope !== "all") return;
  clearError();
  elements.loading.hidden = false;
  elements["empty-state"].hidden = true;
  try {
    renderTasks(await api(`/api/tasks?${buildQuery()}`));
  } catch (error) {
    elements.loading.hidden = true;
    showError(error.message);
  }
}

function updateSelection() {
  elements["selected-count"].textContent = state.selected.size;
  elements["selection-bar"].hidden = state.selected.size === 0;
  elements["batch-assign-button"].disabled = !state.writeEnabled || state.selected.size === 0;
}

function openAssign(ids) {
  state.singleTarget = ids || null;
  const count = ids ? ids.length : state.selected.size;
  elements["assign-description"].textContent = `将${count}张ADM分配给指定人员。`;
  elements["assignee-select"].value = "";
  elements["assign-dialog"].showModal();
}

async function initialize() {
  try {
    const [config, people, health] = await Promise.all([api("/api/config"), api("/api/people"), api("/api/health")]);
    state.people = people.items;
    state.writeEnabled = Boolean(health.writeEnabled);
    state.wecomEnabled = Boolean(config.wecomEnabled);
    renderPeople(config.defaultPerson);
    elements["environment-badge"].textContent = health.dataMode === "mock" ? "演示数据" : (health.writeEnabled ? "数据库已连接 · 可写" : "数据库已连接 · 只读");
    elements["environment-badge"].classList.toggle("live", health.dataMode !== "mock");
    elements["wecom-send-button"].disabled = !state.wecomEnabled;
    elements["wecom-send-button"].title = state.wecomEnabled
      ? "发送该人员全部未结案ADM清单到企业微信群并@本人"
      : "请先在服务器配置企业微信机器人";
    await loadTasks();
  } catch (error) {
    showError(error.message);
  }
}

document.querySelectorAll(".view-tab").forEach(button => button.addEventListener("click", async () => {
  state.scope = button.dataset.scope;
  state.page = 1;
  state.selected.clear();
  document.querySelectorAll(".view-tab").forEach(item => {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  const labels = {
    mine: ["我的ADM待办", `仅展示需要${state.person}处理的未结案ADM。`],
    team: ["团队ADM待办", "查看该负责人名下的未结案ADM，并批量分配实际处理人。"],
    all: ["全部未结案ADM", "查看所有未结案ADM，适用于ADM专员统一分发。"],
  };
  elements["view-title"].textContent = labels[state.scope][0];
  elements["view-description"].textContent = labels[state.scope][1];
  await loadTasks();
}));

elements["person-select"].addEventListener("change", async () => {
  state.person = elements["person-select"].value;
  state.page = 1;
  state.selected.clear();
  if (state.scope === "mine") elements["view-description"].textContent = `仅展示需要${state.person}处理的未结案ADM。`;
  await loadTasks();
});
elements["search-button"].addEventListener("click", () => { state.page = 1; state.selected.clear(); loadTasks(); });
elements["search-input"].addEventListener("keydown", event => { if (event.key === "Enter") { state.page = 1; state.selected.clear(); loadTasks(); } });
elements["source-filter"].addEventListener("change", () => { state.page = 1; state.selected.clear(); loadTasks(); });
elements["alert-filter"].addEventListener("change", () => { state.page = 1; state.selected.clear(); loadTasks(); });
elements["previous-page"].addEventListener("click", () => { if (state.page > 1) { state.page -= 1; state.selected.clear(); loadTasks(); } });
elements["next-page"].addEventListener("click", () => { if (state.page * state.pageSize < state.total) { state.page += 1; state.selected.clear(); loadTasks(); } });
elements["select-all"].addEventListener("change", event => {
  document.querySelectorAll(".row-check").forEach(check => {
    check.checked = event.target.checked;
    const id = Number(check.closest("tr").dataset.id);
    event.target.checked ? state.selected.add(id) : state.selected.delete(id);
  });
  updateSelection();
});
elements["task-body"].addEventListener("change", event => {
  if (!event.target.classList.contains("row-check")) return;
  const id = Number(event.target.closest("tr").dataset.id);
  event.target.checked ? state.selected.add(id) : state.selected.delete(id);
  updateSelection();
});
elements["task-body"].addEventListener("click", event => {
  const button = event.target.closest("[data-transfer]");
  if (button) openAssign([Number(button.dataset.transfer)]);
});
elements["batch-assign-button"].addEventListener("click", () => openAssign(null));
elements["assign-cancel"].addEventListener("click", () => elements["assign-dialog"].close());
elements["assign-form"].addEventListener("submit", async event => {
  event.preventDefault();
  const actualOwner = elements["assignee-select"].value;
  if (!actualOwner) return;
  const admIds = state.singleTarget || [...state.selected];
  try {
    const result = await api("/api/assign", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({admIds, actualOwner, actor: state.person}),
    });
    elements["assign-dialog"].close();
    state.selected.clear();
    showSuccess(`成功分配${result.updatedCount}张ADM给${actualOwner}${result.skipped.length ? `，跳过${result.skipped.length}张` : ""}。`);
    await loadTasks();
  } catch (error) {
    elements["assign-dialog"].close();
    showError(error.message);
  }
});
elements["export-button"].addEventListener("click", () => {
  window.location.href = `/api/export?${buildQuery(true)}`;
});
elements["wecom-send-button"].addEventListener("click", async () => {
  if (!state.person || !state.wecomEnabled) return;
  if (!window.confirm(`确认发送${state.person}全部未结案ADM清单到企业微信？`)) return;
  const button = elements["wecom-send-button"];
  button.disabled = true;
  button.textContent = "正在发送...";
  try {
    const result = await api("/api/wecom/send", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({person: state.person}),
    });
    showSuccess(`已发送${result.taskCount}张未结案ADM给${result.person}${result.mentioned ? "并@本人" : ""}。`);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = !state.wecomEnabled;
    button.textContent = "发送企业微信";
  }
});

initialize();
