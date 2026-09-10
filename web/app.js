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
  pageMode: "assignment",
  recoveryPage: 1,
  recoveryPageSize: 20,
  recoveryTotal: 0,
  recoveryTarget: null,
};

const elements = Object.fromEntries([
  "environment-badge", "sync-time", "person-select", "view-title", "view-description",
  "stat-open", "stat-unassigned", "stat-assigned", "stat-overdue", "stat-due",
  "source-filter", "alert-filter", "search-input", "search-button", "batch-assign-button",
  "export-button", "wecom-send-button", "selection-bar", "selected-count", "success-message", "error-banner",
  "select-all", "task-body", "loading", "empty-state", "result-count", "previous-page",
  "next-page", "page-label", "assign-dialog", "assign-form", "assign-description",
  "assignee-select", "assign-cancel",
  "assignment-nav", "recovery-nav", "import-convert-nav",
  "assignment-page", "recovery-page", "import-convert-page",
  "recovery-file", "recovery-import-button", "recovery-import-result",
  "recovery-status-filter", "recovery-search", "recovery-search-button",
  "recovery-pending", "recovery-processing", "recovery-completed", "recovery-exception",
  "recovery-body", "recovery-loading", "recovery-empty", "recovery-result-count",
  "recovery-previous-page", "recovery-next-page", "recovery-page-label",
  "recovery-dialog", "recovery-form", "recovery-dialog-description",
  "recovery-dialog-status", "recovery-dialog-remark", "recovery-dialog-cancel",
  "import-convert-file", "import-convert-button", "import-convert-result",
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

function switchPage(mode) {
  state.pageMode = mode;
  const recovery = mode === "recovery";
  const conversion = mode === "conversion";
  const assignment = mode === "assignment";
  elements["assignment-page"].hidden = !assignment;
  elements["recovery-page"].hidden = !recovery;
  elements["import-convert-page"].hidden = !conversion;
  elements["assignment-nav"].classList.toggle("active", assignment);
  elements["recovery-nav"].classList.toggle("active", recovery);
  elements["import-convert-nav"].classList.toggle("active", conversion);
  elements["wecom-send-button"].hidden = !assignment;
  if (recovery) loadRecoveryItems();
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function responseFilename(response, fallback) {
  const disposition = response.headers.get("content-disposition") || "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8) return decodeURIComponent(utf8[1]);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

function buildRecoveryQuery() {
  const params = new URLSearchParams({
    page: state.recoveryPage,
    pageSize: state.recoveryPageSize,
  });
  if (elements["recovery-status-filter"].value) params.set("status", elements["recovery-status-filter"].value);
  if (elements["recovery-search"].value.trim()) params.set("search", elements["recovery-search"].value.trim());
  return params.toString();
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
    const transferClass = task.transferAwaitingAcceptance ? "transfer-pending" : (task.transferStatus === "新转入" ? "transfer-new" : "");
    const transferCell = task.lastTransferTime
      ? `<span class="transfer-cell ${transferClass}"><strong>${escapeHtml(task.transferStatus)}</strong><span>${escapeHtml(formatDateTime(task.lastTransferTime))}</span><small>${escapeHtml(task.lastTransferFrom || "未分配")} → ${escapeHtml(task.lastTransferTo || task.actualOwner || "未分配")} · 共${Number(task.transferCount || 0)}次</small></span>`
      : `<span class="muted-text">未发生转单</span>`;
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
      <td>${transferCell}</td>
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

function renderRecoveryItems(data) {
  const statusClass = {
    PENDING: "badge-p1",
    PROCESSING: "badge-p2",
    COMPLETED: "badge-normal",
    EXCEPTION: "badge-p0",
  };
  elements["recovery-body"].innerHTML = data.items.map(item => `
    <tr>
      <td class="adm-number">${escapeHtml(item.adm_no)}</td>
      <td><strong class="recovery-code">${escapeHtml(item.recovery_code)}</strong></td>
      <td><span class="owner-cell"><span>${escapeHtml(item.ota_code || "未配置")}</span><small>${escapeHtml(item.ota_order_no || "-")}</small></span></td>
      <td>${escapeHtml(item.ticket_no || "-")}</td>
      <td>${escapeHtml(item.airline || "未配置")}</td>
      <td><span class="owner-cell"><span>${escapeHtml(item.actual_owner || item.owner || "未分配")}</span><small>原负责人：${escapeHtml(item.owner || "未分配")}</small></span></td>
      <td>${escapeHtml(formatDateTime(item.import_time))}</td>
      <td><span class="badge ${statusClass[item.status] || "badge-normal"}">${escapeHtml(item.statusName)}</span></td>
      <td class="remark-cell">${escapeHtml(item.remark || "-")}</td>
      <td><button class="row-action" type="button" data-recovery-edit="${item.id}" data-adm-no="${escapeHtml(item.adm_no)}" data-status="${escapeHtml(item.status)}" data-remark="${escapeHtml(item.remark || "")}">更新进度</button></td>
    </tr>
  `).join("");
  elements["recovery-loading"].hidden = true;
  elements["recovery-empty"].hidden = data.items.length > 0;
  elements["recovery-pending"].textContent = Number(data.summary.PENDING || 0).toLocaleString("zh-CN");
  elements["recovery-processing"].textContent = Number(data.summary.PROCESSING || 0).toLocaleString("zh-CN");
  elements["recovery-completed"].textContent = Number(data.summary.COMPLETED || 0).toLocaleString("zh-CN");
  elements["recovery-exception"].textContent = Number(data.summary.EXCEPTION || 0).toLocaleString("zh-CN");
  state.recoveryTotal = data.pagination.total;
  const totalPages = Math.max(1, Math.ceil(state.recoveryTotal / state.recoveryPageSize));
  elements["recovery-result-count"].textContent = `共${state.recoveryTotal.toLocaleString("zh-CN")}条`;
  elements["recovery-page-label"].textContent = `第${state.recoveryPage}页 / 共${totalPages}页`;
  elements["recovery-previous-page"].disabled = state.recoveryPage <= 1;
  elements["recovery-next-page"].disabled = state.recoveryPage >= totalPages;
}

async function loadRecoveryItems() {
  clearError();
  elements["recovery-loading"].hidden = false;
  elements["recovery-empty"].hidden = true;
  try {
    renderRecoveryItems(await api(`/api/recovery?${buildRecoveryQuery()}`));
  } catch (error) {
    elements["recovery-loading"].hidden = true;
    showError(error.message);
  }
}

function openRecoveryDialog(button) {
  state.recoveryTarget = Number(button.dataset.recoveryEdit);
  elements["recovery-dialog-description"].textContent = `ADM ${button.dataset.admNo} 的编码恢复进度。`;
  elements["recovery-dialog-status"].value = button.dataset.status;
  elements["recovery-dialog-remark"].value = button.dataset.remark || "";
  elements["recovery-dialog"].showModal();
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

elements["assignment-nav"].addEventListener("click", () => switchPage("assignment"));
elements["recovery-nav"].addEventListener("click", () => switchPage("recovery"));
elements["import-convert-nav"].addEventListener("click", () => switchPage("conversion"));
elements["recovery-search-button"].addEventListener("click", () => { state.recoveryPage = 1; loadRecoveryItems(); });
elements["recovery-search"].addEventListener("keydown", event => {
  if (event.key === "Enter") { state.recoveryPage = 1; loadRecoveryItems(); }
});
elements["recovery-status-filter"].addEventListener("change", () => { state.recoveryPage = 1; loadRecoveryItems(); });
elements["recovery-previous-page"].addEventListener("click", () => {
  if (state.recoveryPage > 1) { state.recoveryPage -= 1; loadRecoveryItems(); }
});
elements["recovery-next-page"].addEventListener("click", () => {
  if (state.recoveryPage * state.recoveryPageSize < state.recoveryTotal) { state.recoveryPage += 1; loadRecoveryItems(); }
});
elements["recovery-import-button"].addEventListener("click", () => elements["recovery-file"].click());
elements["recovery-file"].addEventListener("change", async () => {
  const file = elements["recovery-file"].files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("operator", state.person || "ADM专员");
  const button = elements["recovery-import-button"];
  button.disabled = true;
  button.textContent = "正在导入...";
  try {
    const result = await api("/api/recovery/import", {method: "POST", body: form});
    const warnings = result.missingAdmNumbers.length + result.invalidRows.length;
    elements["recovery-import-result"].textContent = `导入${result.importedCount}条${warnings ? `，${warnings}条需核对` : ""}`;
    showSuccess(`恢复编码导入完成：新增${result.createdCount}条，编码变更重置${result.resetCount}条。`);
    if (warnings) {
      const missing = result.missingAdmNumbers.slice(0, 5).join("、");
      const invalid = result.invalidRows.slice(0, 5).map(item => `第${item.row}行${item.reason}`).join("；");
      showError(`部分记录未导入。${missing ? `未找到ADM：${missing}。` : ""}${invalid}`);
    }
    state.recoveryPage = 1;
    await loadRecoveryItems();
  } catch (error) {
    showError(error.message);
  } finally {
    elements["recovery-file"].value = "";
    button.disabled = false;
    button.textContent = "导入填写后的Excel";
  }
});
elements["recovery-body"].addEventListener("click", event => {
  const button = event.target.closest("[data-recovery-edit]");
  if (button) openRecoveryDialog(button);
});
elements["recovery-dialog-cancel"].addEventListener("click", () => elements["recovery-dialog"].close());
elements["recovery-form"].addEventListener("submit", async event => {
  event.preventDefault();
  const status = elements["recovery-dialog-status"].value;
  const remark = elements["recovery-dialog-remark"].value.trim();
  if (status === "EXCEPTION" && !remark) {
    showError("标记异常时必须填写处理备注");
    return;
  }
  try {
    await api(`/api/recovery/${state.recoveryTarget}`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({status, remark, handler: state.person || "ADM专员"}),
    });
    elements["recovery-dialog"].close();
    showSuccess("编码恢复进度已更新。");
    await loadRecoveryItems();
  } catch (error) {
    showError(error.message);
  }
});

elements["import-convert-button"].addEventListener("click", () => elements["import-convert-file"].click());
elements["import-convert-file"].addEventListener("change", async () => {
  const file = elements["import-convert-file"].files[0];
  if (!file) return;
  clearError();
  const form = new FormData();
  form.append("file", file);
  const button = elements["import-convert-button"];
  button.disabled = true;
  button.textContent = "正在读取数据库并转换...";
  elements["import-convert-result"].textContent = file.name;
  try {
    const response = await fetch("/api/adm-import/convert", {method: "POST", body: form});
    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      const body = contentType.includes("application/json") ? await response.json() : null;
      throw new Error(body?.message || `转换失败：${response.status}`);
    }
    const filename = responseFilename(response, `ADM管理导入_${new Date().toISOString().slice(0, 10).replaceAll("-", "")}.xlsx`);
    downloadBlob(await response.blob(), filename);
    elements["import-convert-result"].textContent = `已生成：${filename}`;
    showSuccess("转换完成。请核对下载文件后导入ADM管理系统。");
  } catch (error) {
    elements["import-convert-result"].textContent = "转换未完成";
    showError(error.message);
  } finally {
    elements["import-convert-file"].value = "";
    button.disabled = false;
    button.textContent = "选择文件并转换";
  }
});

initialize();
