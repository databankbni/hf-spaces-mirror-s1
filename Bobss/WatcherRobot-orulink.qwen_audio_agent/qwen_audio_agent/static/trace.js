const statusLabels = { ready: "READY", update: "UPDATE", error: "ERROR" };
const componentCards = new Map(
  [...document.querySelectorAll("[data-component]")].map((node) => [node.dataset.component, node]),
);
const traceList = document.querySelector("#trace-list");
const livePill = document.querySelector("#live-pill");
const toggleButton = document.querySelector("#toggle-live");
const clearButton = document.querySelector("#clear-trace");
const lastSync = document.querySelector("#last-sync");
const uptime = document.querySelector("#uptime");
const pairingForm = document.querySelector("#pairing-form");
const pairingCode = document.querySelector("#pairing-code");
const pairButton = document.querySelector("#pair-device");
const cancelButton = document.querySelector("#cancel-pairing");
const disconnectButton = document.querySelector("#disconnect-device");
const deviceBadge = document.querySelector("#device-badge");
const deviceDetail = document.querySelector("#device-detail");
const pairingFeedback = document.querySelector("#pairing-feedback");
const gatewaySettingsForm = document.querySelector("#gateway-settings-form");
const gatewaySettingsFeedback = document.querySelector("#gateway-settings-feedback");
const saveGatewayButton = document.querySelector("#save-gateway-settings");
const resetGatewayButton = document.querySelector("#reset-gateway-settings");
const saveRestartGatewayButton = document.querySelector("#save-restart-gateway-settings");
const gatewayRuntimeStatus = document.querySelector("#gateway-runtime-status");
const realtimeRuntimeStatus = document.querySelector("#realtime-runtime-status");
const backendRuntimeStatus = document.querySelector("#backend-runtime-status");
const dashscopeKeyStatus = document.querySelector("#dashscope-key-status");
const backendCredentialStatus = document.querySelector("#backend-credential-status");
const vadSettingsForm = document.querySelector("#vad-settings-form");
const vadSettingsFeedback = document.querySelector("#vad-settings-feedback");
const saveVadButton = document.querySelector("#save-vad-settings");
const resetVadButton = document.querySelector("#reset-vad-settings");
const restartServicesButton = document.querySelector("#restart-services");
const touchSettingsForm = document.querySelector("#touch-interrupt-settings-form");
const touchSettingsFeedback = document.querySelector("#touch-interrupt-settings-feedback");
const saveTouchButton = document.querySelector("#save-touch-interrupt-settings");
const resetTouchButton = document.querySelector("#reset-touch-interrupt-settings");
const rmsMeter = document.querySelector("#rms-meter");
const rmsValue = document.querySelector("#rms-value");
const rmsPeak = document.querySelector("#rms-peak");
const rmsState = document.querySelector("#rms-state");
const rmsLevel = document.querySelector("#rms-level");
const rmsTrack = rmsMeter.querySelector(".rms-track");
const rmsStartMarker = document.querySelector("#rms-start-marker");
const rmsStopMarker = document.querySelector("#rms-stop-marker");
const vadFields = {
  enabled: document.querySelector("#vad-enabled"),
  start_rms: document.querySelector("#vad-start-rms"),
  stop_rms: document.querySelector("#vad-stop-rms"),
  start_frames: document.querySelector("#vad-start-frames"),
  silence_ms: document.querySelector("#vad-silence-ms"),
  pre_roll_ms: document.querySelector("#vad-pre-roll-ms"),
  max_utterance_ms: document.querySelector("#vad-max-utterance-ms"),
};
const touchFields = {
  enabled: document.querySelector("#touch-interrupt-enabled"),
  back_touch: document.querySelector("#touch-interrupt-back"),
  screen_touch: document.querySelector("#touch-interrupt-screen"),
  debounce_ms: document.querySelector("#touch-interrupt-debounce"),
};
const gatewayFields = {
  dashscope_api_key: document.querySelector("#dashscope-api-key"),
  clear_dashscope_api_key: document.querySelector("#clear-dashscope-api-key"),
  realtime_model: document.querySelector("#realtime-model"),
  agent_protocol: document.querySelector("#agent-protocol"),
  backend_model: document.querySelector("#backend-model"),
  backend_permission_mode: document.querySelector("#backend-permission-mode"),
  backend_ownership: document.querySelector("#backend-ownership"),
  backend_url: document.querySelector("#backend-url"),
  backend_credential: document.querySelector("#backend-credential"),
  clear_backend_credential: document.querySelector("#clear-backend-credential"),
};
let loadedGatewaySettings = null;
let gatewayCatalogs = null;
let defaultVadSettings = null;
let defaultTouchSettings = null;
let live = true;
let events = [];
let daemonControlUrl = null;
let pairingTargetMode = null;
let diagnosticsInstanceId = null;
let deviceActionPending = false;
let settingsActionPending = false;
let gatewayRuntimePollPending = false;
const RMS_DISPLAY_MAX = 3000;

function rmsPosition(value) {
  const numericValue = Math.max(0, Number(value) || 0);
  return `${Math.min(100, (numericValue / RMS_DISPLAY_MAX) * 100)}%`;
}

function updateRmsThresholds() {
  rmsStartMarker.style.left = rmsPosition(vadFields.start_rms.value);
  rmsStopMarker.style.left = rmsPosition(vadFields.stop_rms.value);
}

function updateRmsMeter(sample) {
  const value = Number(sample?.value) || 0;
  const peak = Number(sample?.peak) || 0;
  const hasSamples = (Number(sample?.sample_count) || 0) > 0;
  const inSpeech = Boolean(sample?.in_speech);
  rmsValue.value = String(value);
  rmsPeak.textContent = String(peak);
  rmsLevel.style.width = rmsPosition(value);
  rmsTrack.setAttribute("aria-valuenow", String(value));
  rmsMeter.dataset.state = inSpeech ? "speech" : hasSamples ? "monitoring" : "idle";
  rmsState.textContent = inSpeech ? "正在采集语音" : hasSamples ? "VAD 正在监听" : "等待麦克风采样";
}

function updateStatus(snapshot) {
  for (const [name, card] of componentCards) {
    const status = snapshot.components[name];
    if (!status) continue;
    card.dataset.state = status.state;
    card.querySelector("strong").textContent = statusLabels[status.state] || "UPDATE";
    card.querySelector("small").textContent = status.detail || "无详细信息";
  }
  uptime.textContent = `运行 ${Math.floor(snapshot.uptime_seconds)} 秒`;
  lastSync.textContent = `最近同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function makeText(tag, className, value) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = value;
  return node;
}

function renderTrace() {
  traceList.replaceChildren();
  if (!events.length) {
    const empty = makeText("div", "empty-state", "");
    empty.append(makeText("b", "", "等待第一轮语音"), makeText("span", "", "连接准备完成后，链路事件会自动出现在这里。"));
    traceList.append(empty);
    return;
  }
  const groups = new Map();
  for (const event of events) {
    const key = event.turn_id === null ? "system" : String(event.turn_id);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  for (const [key, group] of [...groups].reverse()) {
    const card = document.createElement("article");
    card.className = `turn${group.some((event) => event.level === "error") ? " has-error" : ""}`;
    const head = document.createElement("div");
    head.className = "turn-head";
    head.append(
      makeText("strong", "", key === "system" ? "系统链路" : `语音轮次 #${key}`),
      makeText("time", "", new Date(group[0].timestamp).toLocaleTimeString("zh-CN", { hour12: false })),
    );
    card.append(head);
    for (const event of group) {
      const row = document.createElement("div");
      row.className = "event-row";
      row.dataset.level = event.level;
      const stage = makeText("span", "event-stage", event.stage);
      stage.prepend(makeText("i", "level-dot", ""));
      const detail = makeText("span", "event-detail", event.detail || "—");
      const metricText = Object.entries(event.metrics || {}).map(([name, value]) => `${name}=${value}`).join("  ");
      row.append(stage, detail, makeText("span", "event-metrics", metricText));
      card.append(row);
    }
    traceList.append(card);
  }
}

async function poll() {
  if (!live) return;
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    events = snapshot.events;
    updateStatus(snapshot);
    updateRmsMeter(snapshot.rms);
    renderTrace();
    livePill.classList.remove("offline");
    livePill.querySelector("b").textContent = "实时更新";
  } catch (error) {
    livePill.classList.add("offline");
    livePill.querySelector("b").textContent = "诊断服务断开";
    lastSync.textContent = `同步失败：${error.message}`;
  }
}

function setPairingFeedback(message, isError = false) {
  pairingFeedback.textContent = message;
  pairingFeedback.classList.toggle("error", isError);
}

function setGatewayFeedback(message, isError = false) {
  gatewaySettingsFeedback.textContent = message;
  gatewaySettingsFeedback.classList.toggle("error", isError);
}

function setVadFeedback(message, isError = false) {
  vadSettingsFeedback.textContent = message;
  vadSettingsFeedback.classList.toggle("error", isError);
}

function setTouchFeedback(message, isError = false) {
  touchSettingsFeedback.textContent = message;
  touchSettingsFeedback.classList.toggle("error", isError);
}

function setSettingsBusy(busy) {
  settingsActionPending = busy;
  saveVadButton.disabled = busy;
  resetVadButton.disabled = busy;
  restartServicesButton.disabled = busy;
  for (const field of Object.values(vadFields)) field.disabled = busy;
  saveTouchButton.disabled = busy;
  resetTouchButton.disabled = busy;
  for (const field of Object.values(touchFields)) field.disabled = busy;
  saveGatewayButton.disabled = busy;
  resetGatewayButton.disabled = busy;
  saveRestartGatewayButton.disabled = busy;
  for (const field of Object.values(gatewayFields)) field.disabled = busy;
  if (!busy) updateBackendFieldVisibility();
}

function populateSelect(select, items, value) {
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label;
    select.append(option);
  }
  select.value = value;
}

function selectedBackendDefinition() {
  return gatewayCatalogs?.backends?.find(
    (item) => item.id === gatewayFields.agent_protocol.value,
  ) || null;
}

function updateBackendFieldVisibility() {
  const backend = selectedBackendDefinition();
  const enabled = gatewayFields.agent_protocol.value !== "none";
  const supportsExternal = backend?.supports_external === true;
  const external = enabled && supportsExternal
    && gatewayFields.backend_ownership.value === "external";
  gatewayFields.backend_model.disabled = settingsActionPending || !enabled;
  gatewayFields.backend_permission_mode.disabled = settingsActionPending || !enabled;
  gatewayFields.backend_ownership.disabled = settingsActionPending || !enabled;
  const externalOption = gatewayFields.backend_ownership.querySelector('option[value="external"]');
  if (externalOption) externalOption.disabled = !supportsExternal;
  if (!supportsExternal && gatewayFields.backend_ownership.value === "external") {
    gatewayFields.backend_ownership.value = "owned";
  }
  for (const node of document.querySelectorAll(".external-backend-field")) {
    node.hidden = !external;
  }
  gatewayFields.backend_url.disabled = settingsActionPending || !external;
  gatewayFields.backend_credential.disabled = settingsActionPending || !external;
  gatewayFields.clear_backend_credential.disabled = settingsActionPending || !external;
}

function renderGatewayRuntime(gateway) {
  const realtime = gateway?.realtime || {};
  const backend = gateway?.backend || {};
  gatewayRuntimeStatus.dataset.state = gateway?.ok ? "ready" : "error";
  gatewayRuntimeStatus.textContent = gateway?.ok ? "运行中" : "不可用";
  realtimeRuntimeStatus.dataset.state = realtime.connected ? "ready" : "update";
  realtimeRuntimeStatus.textContent = realtime.connected
    ? `${realtime.model || "Realtime"} · 已连接`
    : `${realtime.model || "Realtime"} · 未连接`;
  const backendEnabled = backend.enabled && backend.protocol !== "none";
  backendRuntimeStatus.dataset.state = backend.connected ? "ready" : backendEnabled ? "update" : "idle";
  backendRuntimeStatus.textContent = backendEnabled
    ? `${backend.protocol || "Agent"} · ${backend.connected ? "已连接" : backend.status || "未连接"}`
    : "仅前台聊天";
}

function renderGatewaySettings(payload) {
  const settings = payload.settings;
  loadedGatewaySettings = { ...settings };
  gatewayCatalogs = payload.catalogs;
  populateSelect(gatewayFields.realtime_model, gatewayCatalogs.realtime_models, settings.realtime_model);
  populateSelect(gatewayFields.agent_protocol, gatewayCatalogs.backends, settings.agent_protocol);
  gatewayFields.backend_model.value = settings.backend_model || "";
  gatewayFields.backend_permission_mode.value = settings.backend_permission_mode;
  gatewayFields.backend_ownership.value = settings.backend_ownership;
  gatewayFields.backend_url.value = settings.backend_url || "";
  gatewayFields.dashscope_api_key.value = "";
  gatewayFields.backend_credential.value = "";
  gatewayFields.clear_dashscope_api_key.checked = false;
  gatewayFields.clear_backend_credential.checked = false;
  dashscopeKeyStatus.textContent = settings.dashscope_api_key_configured ? "已配置" : "未配置";
  backendCredentialStatus.textContent = settings.backend_credential_configured ? "已配置" : "未配置";
  renderGatewayRuntime(payload.gateway);
  updateBackendFieldVisibility();
}

function readGatewaySettings() {
  if (!gatewaySettingsForm.reportValidity()) {
    throw new Error("请先修正 Gateway 配置。");
  }
  const protocol = gatewayFields.agent_protocol.value;
  const backend = selectedBackendDefinition();
  const ownership = protocol === "none" ? "owned" : gatewayFields.backend_ownership.value;
  if (ownership === "external" && backend?.supports_external !== true) {
    throw new Error("当前后台 Agent 不支持外部连接。");
  }
  const payload = {
    realtime_model: gatewayFields.realtime_model.value,
    agent_protocol: protocol,
    backend_model: protocol === "none" ? "" : gatewayFields.backend_model.value.trim(),
    backend_permission_mode: protocol === "none" ? "native" : gatewayFields.backend_permission_mode.value,
    backend_ownership: ownership,
    backend_url: ownership === "external" ? gatewayFields.backend_url.value.trim() : "",
  };
  const apiKey = gatewayFields.dashscope_api_key.value.trim();
  const credential = gatewayFields.backend_credential.value.trim();
  if (!loadedGatewaySettings?.dashscope_api_key_configured && !apiKey
    && !gatewayFields.clear_dashscope_api_key.checked) {
    throw new Error("请填写 DashScope API Key。");
  }
  if (gatewayFields.clear_dashscope_api_key.checked) payload.clear_dashscope_api_key = true;
  else if (apiKey) payload.dashscope_api_key = apiKey;
  if (gatewayFields.clear_backend_credential.checked) payload.clear_backend_credential = true;
  else if (credential) payload.backend_credential = credential;
  return payload;
}

function renderTouchSettings(settings) {
  touchFields.enabled.checked = Boolean(settings.enabled);
  touchFields.back_touch.checked = settings.sources.includes("back_touch");
  touchFields.screen_touch.checked = settings.sources.includes("screen_touch");
  touchFields.debounce_ms.value = String(settings.debounce_ms);
}

function readTouchSettings() {
  if (!touchSettingsForm.reportValidity()) {
    throw new Error("请先修正超出范围的触摸打断参数。");
  }
  const sources = [];
  if (touchFields.back_touch.checked) sources.push("back_touch");
  if (touchFields.screen_touch.checked) sources.push("screen_touch");
  if (!sources.length) throw new Error("请至少选择一种触摸来源。");
  return {
    enabled: touchFields.enabled.checked,
    sources,
    debounce_ms: Number(touchFields.debounce_ms.value),
  };
}

function renderVadSettings(settings) {
  vadFields.enabled.checked = Boolean(settings.enabled);
  for (const [name, field] of Object.entries(vadFields)) {
    if (name !== "enabled") field.value = String(settings[name]);
  }
  updateRmsThresholds();
}

function readVadSettings() {
  const settings = { enabled: vadFields.enabled.checked };
  for (const [name, field] of Object.entries(vadFields)) {
    if (name !== "enabled") settings[name] = Number(field.value);
  }
  if (!vadSettingsForm.reportValidity()) throw new Error("请先修正超出范围的 VAD 参数。");
  if (settings.stop_rms > settings.start_rms) throw new Error("结束 RMS 不能高于开始 RMS。");
  return settings;
}

async function settingsRequest(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadGatewaySettings() {
  try {
    const payload = await settingsRequest("/api/settings/gateway");
    renderGatewaySettings(payload);
    setGatewayFeedback(payload.restart_required
      ? "配置已保存但尚未生效，请重启应用服务。"
      : "当前配置与运行实例一致。");
  } catch (error) {
    setGatewayFeedback(`读取失败：${error.message}`, true);
  }
}

async function pollGatewayRuntime() {
  if (gatewayRuntimePollPending) return;
  gatewayRuntimePollPending = true;
  try {
    const payload = await settingsRequest("/api/status/gateway");
    renderGatewayRuntime(payload.gateway);
  } catch (_error) {
    renderGatewayRuntime({
      ok: false,
      realtime: { connected: false },
      backend: { enabled: false, connected: false },
    });
  } finally {
    gatewayRuntimePollPending = false;
  }
}

async function saveGatewaySettings() {
  const payload = await settingsRequest("/api/settings/gateway", {
    method: "PUT",
    body: JSON.stringify(readGatewaySettings()),
  });
  renderGatewaySettings(payload);
  return payload;
}

async function loadVadSettings() {
  try {
    const payload = await settingsRequest("/api/settings/vad");
    defaultVadSettings = payload.defaults;
    renderVadSettings(payload.settings);
    setVadFeedback(payload.restart_required
      ? "参数已保存但尚未生效，请重启相关服务。"
      : "当前参数已加载。修改并保存后，需要重启相关服务才能生效。");
  } catch (error) {
    setVadFeedback(`读取失败：${error.message}`, true);
  }
}

async function loadTouchSettings() {
  try {
    const payload = await settingsRequest("/api/settings/touch-interrupt");
    defaultTouchSettings = payload.defaults;
    renderTouchSettings(payload.settings);
    setTouchFeedback(payload.restart_required
      ? "参数已保存但尚未生效，请重启 Application。"
      : "当前参数已加载。保存后需要重启 Application 才能生效。");
  } catch (error) {
    setTouchFeedback(`读取失败：${error.message}`, true);
  }
}

function renderDevice(device) {
  const state = device.state || "idle";
  const labels = {
    idle: "未连接",
    discovering: "发现设备",
    connecting: "正在连接",
    connected: "已连接",
  };
  deviceBadge.dataset.state = state === "idle" && device.last_error ? "error" : state;
  deviceBadge.textContent = labels[state] || state.toUpperCase();
  deviceDetail.textContent = device.online
    ? `设备在线 · 模式 ${device.mode || "SDK"}`
    : device.last_error || (state === "idle" ? "输入机器人显示的六位配对码。" : "SDK Daemon 正在建立设备链路。");
  const pairing = state === "discovering" || state === "connecting";
  const connected = state === "connected";
  pairingCode.disabled = pairing || connected || deviceActionPending;
  pairButton.hidden = pairing || connected;
  pairButton.disabled = deviceActionPending;
  cancelButton.hidden = !pairing;
  cancelButton.disabled = deviceActionPending;
  disconnectButton.hidden = !connected;
  disconnectButton.disabled = deviceActionPending;
}

async function daemonRequest(path, options = {}) {
  if (!daemonControlUrl) throw new Error("SDK Daemon 地址尚未就绪");
  const response = await fetch(`${daemonControlUrl}${path}`, {
    cache: "no-store",
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
  return payload;
}

async function pollDevice() {
  if (!live || !daemonControlUrl || deviceActionPending) return;
  try {
    const payload = await daemonRequest("/daemon/devices");
    renderDevice(payload.device || {});
  } catch (error) {
    deviceBadge.dataset.state = "error";
    deviceBadge.textContent = "DAEMON 离线";
    deviceDetail.textContent = error.message;
  }
}

async function performDeviceAction(action, successMessage) {
  deviceActionPending = true;
  setPairingFeedback("正在提交 SDK Daemon…");
  try {
    await action();
    setPairingFeedback(successMessage);
  } catch (error) {
    setPairingFeedback(error.message, true);
  } finally {
    deviceActionPending = false;
    await pollDevice();
  }
}

toggleButton.addEventListener("click", () => {
  live = !live;
  toggleButton.textContent = live ? "暂停" : "继续";
  if (live) poll();
});

clearButton.addEventListener("click", async () => {
  const response = await fetch("/api/traces/clear", { method: "POST" });
  if (response.ok) {
    events = [];
    renderTrace();
  }
});

pairingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = pairingCode.value.trim();
  if (!/^\d{6}$/.test(code)) {
    setPairingFeedback("请输入机器人显示的六位数字配对码。", true);
    pairingCode.focus();
    return;
  }
  await performDeviceAction(
    () => daemonRequest("/daemon/devices/pair", {
      method: "POST",
      body: JSON.stringify({ pairing_code: code, target_mode: pairingTargetMode }),
    }),
    "配对请求已提交，正在等待设备连接。",
  );
  pairingCode.value = "";
});

cancelButton.addEventListener("click", () => performDeviceAction(
  () => daemonRequest("/daemon/devices/pair/cancel", { method: "POST" }),
  "已取消本次配对。",
));

disconnectButton.addEventListener("click", () => performDeviceAction(
  () => daemonRequest("/daemon/devices/disconnect", { method: "POST" }),
  "设备连接已断开。",
));

gatewaySettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (settingsActionPending) return;
  try {
    setSettingsBusy(true);
    setGatewayFeedback("正在安全保存 Gateway 配置…");
    await saveGatewaySettings();
    setGatewayFeedback("配置已保存。重启应用服务后生效。");
  } catch (error) {
    setGatewayFeedback(error.message, true);
  } finally {
    setSettingsBusy(false);
  }
});

resetGatewayButton.addEventListener("click", () => {
  if (!loadedGatewaySettings) {
    setGatewayFeedback("当前配置尚未加载，请稍后重试。", true);
    return;
  }
  loadGatewaySettings();
});

gatewayFields.agent_protocol.addEventListener("change", updateBackendFieldVisibility);
gatewayFields.backend_ownership.addEventListener("change", updateBackendFieldVisibility);

saveRestartGatewayButton.addEventListener("click", async () => {
  if (settingsActionPending) return;
  if (!window.confirm("将保留 SDK Daemon 与机器人连接，仅重启 Gateway 和 Application，语音服务会短暂中断。是否继续？")) return;
  try {
    setSettingsBusy(true);
    setGatewayFeedback("正在保存配置…");
    await saveGatewaySettings();
    await restartManagedServices();
  } catch (error) {
    setGatewayFeedback(`保存或重启失败：${error.message}`, true);
  } finally {
    setSettingsBusy(false);
  }
});

vadSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (settingsActionPending) return;
  try {
    const settings = readVadSettings();
    setSettingsBusy(true);
    setVadFeedback("正在保存 VAD 参数…");
    const payload = await settingsRequest("/api/settings/vad", {
      method: "PUT",
      body: JSON.stringify(settings),
    });
    renderVadSettings(payload.settings);
    setVadFeedback("参数已保存。点击“重启相关服务”应用新参数。");
  } catch (error) {
    setVadFeedback(error.message, true);
  } finally {
    setSettingsBusy(false);
  }
});

resetVadButton.addEventListener("click", () => {
  if (!defaultVadSettings) {
    setVadFeedback("默认参数尚未加载，请稍后重试。", true);
    return;
  }
  renderVadSettings(defaultVadSettings);
  setVadFeedback("已载入默认值，尚未保存。", false);
});

touchSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (settingsActionPending) return;
  try {
    const settings = readTouchSettings();
    setSettingsBusy(true);
    setTouchFeedback("正在保存触摸打断参数…");
    const payload = await settingsRequest("/api/settings/touch-interrupt", {
      method: "PUT",
      body: JSON.stringify(settings),
    });
    renderTouchSettings(payload.settings);
    setTouchFeedback("参数已保存。点击“重启 Application”应用新参数。");
  } catch (error) {
    setTouchFeedback(error.message, true);
  } finally {
    setSettingsBusy(false);
  }
});

resetTouchButton.addEventListener("click", () => {
  if (!defaultTouchSettings) {
    setTouchFeedback("默认参数尚未加载，请稍后重试。", true);
    return;
  }
  renderTouchSettings(defaultTouchSettings);
  setTouchFeedback("已载入默认值，尚未保存。", false);
});

vadFields.start_rms.addEventListener("input", updateRmsThresholds);
vadFields.stop_rms.addEventListener("input", updateRmsThresholds);

restartServicesButton.addEventListener("click", async () => {
  if (settingsActionPending) return;
  if (!window.confirm("将保留 SDK Daemon 与机器人连接，仅重启 Gateway 和 Application，语音服务会短暂中断。是否继续？")) return;
  try {
    setSettingsBusy(true);
    await restartManagedServices();
  } catch (error) {
    setVadFeedback(`重启失败：${error.message}`, true);
  } finally {
    setSettingsBusy(false);
  }
});

async function restartManagedServices() {
  const previousInstanceId = diagnosticsInstanceId;
  let deviceWasOnline = false;
  try {
    const payload = await daemonRequest("/daemon/devices");
    deviceWasOnline = Boolean(payload.device?.online);
  } catch (_error) {
    // Daemon 可用性仍会由重启请求和恢复轮询给出准确错误。
  }
  setGatewayFeedback("正在保留机器人连接并重启 Gateway 与 Application，页面会短暂断开并自动恢复。");
  setVadFeedback("正在重启应用服务…");
  await settingsRequest("/api/services/restart", {
    method: "POST",
    body: "{}",
  });
  diagnosticsInstanceId = await waitForDiagnosticsRecovery(previousInstanceId, deviceWasOnline);
  await Promise.all([loadGatewaySettings(), loadVadSettings(), loadTouchSettings()]);
  setGatewayFeedback("服务已重启，Gateway 与 Agent 配置已生效。");
  setVadFeedback("服务已重启，新 VAD 参数已生效。");
  setTouchFeedback("服务已重启，新触摸打断参数已生效。");
}

async function waitForDiagnosticsRecovery(previousInstanceId, deviceWasOnline = false) {
  const deadline = Date.now() + 60000;
  let lastError = "Application 尚未恢复";
  while (Date.now() < deadline) {
    try {
      const [configResponse, status, devices] = await Promise.all([
        fetch("/api/config", { cache: "no-store" }),
        daemonRequest("/daemon/status"),
        daemonRequest("/daemon/devices"),
      ]);
      if (!configResponse.ok) throw new Error(`诊断服务 HTTP ${configResponse.status}`);
      const config = await configResponse.json();
      const application = status.application || {};
      if (
        application.state === "running"
        && config.diagnostics_instance_id
        && config.diagnostics_instance_id !== previousInstanceId
        && (!deviceWasOnline || devices.device?.online === true)
      ) {
        return config.diagnostics_instance_id;
      }
      if (deviceWasOnline && devices.device?.online !== true) {
        lastError = "重启前机器人在线，但当前设备连接已丢失";
      } else {
        lastError = application.state === "running"
          ? "仍在等待新的诊断服务实例"
          : `Application 状态为 ${application.state || "unknown"}`;
      }
    } catch (error) {
      lastError = error.message;
      // Application 正在重启，等待诊断服务恢复。
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`诊断页面在 60 秒内未恢复：${lastError}`);
}

async function initializeDeviceControl() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    daemonControlUrl = config.daemon_control_url;
    pairingTargetMode = config.pairing_target_mode;
    diagnosticsInstanceId = config.diagnostics_instance_id;
    await pollDevice();
  } catch (error) {
    deviceBadge.dataset.state = "error";
    deviceBadge.textContent = "配置错误";
    deviceDetail.textContent = error.message;
  }
}

poll();
initializeDeviceControl();
loadVadSettings();
loadTouchSettings();
loadGatewaySettings();
pollGatewayRuntime();
setInterval(poll, 1000);
setInterval(pollDevice, 1000);
setInterval(pollGatewayRuntime, 1000);
