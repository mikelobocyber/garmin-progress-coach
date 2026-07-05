const $ = (id) => document.getElementById(id);

const STORAGE_KEYS = {
  openaiKey: "garminCoach.openaiKey",
  openaiModel: "garminCoach.openaiModel",
  serverToken: "garminCoach.serverToken",
};

function fmt(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function toDateInputValue(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function prettyDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function setStatus(id, message, kind = "") {
  const el = $(id);
  el.textContent = message;
  el.classList.remove("ok", "error");
  if (kind) el.classList.add(kind);
}

function getSavedSettings() {
  return {
    openaiKey: localStorage.getItem(STORAGE_KEYS.openaiKey) || "",
    openaiModel: localStorage.getItem(STORAGE_KEYS.openaiModel) || "gpt-4.1-mini",
    serverToken: localStorage.getItem(STORAGE_KEYS.serverToken) || "",
  };
}

function loadSavedSettingsIntoForm() {
  const settings = getSavedSettings();
  $("openaiKey").value = settings.openaiKey;
  $("openaiModel").value = settings.openaiModel;
  $("serverToken").value = settings.serverToken;
}

function saveSettingsFromForm() {
  localStorage.setItem(STORAGE_KEYS.openaiKey, $("openaiKey").value.trim());
  localStorage.setItem(STORAGE_KEYS.openaiModel, $("openaiModel").value.trim() || "gpt-4.1-mini");
  localStorage.setItem(STORAGE_KEYS.serverToken, $("serverToken").value.trim());
}

function clearSavedSettings() {
  Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
  loadSavedSettingsIntoForm();
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getSavedSettings().serverToken;
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Can't reach the app. Is the server still running?");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error("This server requires APP_SECRET_TOKEN. Paste the server API token in Settings, save it, then refresh.");
    }
    throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
  }
  return body;
}

// All table cells are built with textContent (never innerHTML) so a CSV
// containing HTML in a title can't inject markup into the page.
function activityRow(activity) {
  const row = document.createElement("tr");
  const cells = [
    prettyDate(activity.start_time),
    fmt(activity.category_label),
    fmt(activity.activity_type),
    fmt(activity.title),
    activity.distance_miles ?? "—",
    fmt(activity.duration),
    fmt(activity.avg_pace),
    fmt(activity.avg_hr),
  ];
  for (const value of cells) {
    const td = document.createElement("td");
    td.textContent = value;
    row.appendChild(td);
  }
  return row;
}

function emptyTableRow(message) {
  const row = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = 8;
  td.className = "empty-row";
  td.textContent = message;
  row.appendChild(td);
  return row;
}

function renderTrainingMix(mix) {
  const container = $("trainingMix");
  container.replaceChildren();
  if (!mix || mix.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted-text";
    empty.textContent = "No training mix yet. Upload a Garmin CSV to see categories like running, strength, cardio, cycling, walking, or mobility.";
    container.appendChild(empty);
    return;
  }

  for (const item of mix) {
    const row = document.createElement("div");
    row.className = "mix-row";

    const label = document.createElement("strong");
    label.textContent = item.label;

    const detail = document.createElement("span");
    const miles = item.miles ? `, ${item.miles} mi` : "";
    const hr = item.avg_hr ? `, avg HR ${item.avg_hr}` : "";
    detail.textContent = `${item.sessions} session(s), ${item.minutes} min${miles}${hr}`;

    row.append(label, detail);
    container.appendChild(row);
  }
}

async function loadDashboard() {
  const [summary, projection] = await Promise.all([
    api("/api/summary/latest"),
    api("/api/training/projection"),
  ]);

  const hasData = (summary.activity_count_total || 0) > 0;

  $("trainingStatus").textContent = hasData ? fmt(projection.status) : "No data yet";
  $("goalText").textContent = `2-mile marker: ${fmt(summary.current_two_mile_marker)} · goal: ${fmt(summary.goal_two_mile)}`;
  $("recentSessions").textContent = fmt(summary.recent_activity_count, "0");
  $("recentMinutes").textContent = fmt(summary.recent_activity_minutes, "0");
  $("strengthSessions").textContent = fmt(summary.recent_strength_sessions, "0");
  $("cardioSessions").textContent = fmt(summary.recent_cardio_sessions, "0");
  $("recentRuns").textContent = fmt(summary.recent_runs, "0");
  $("recentMiles").textContent = fmt(summary.recent_run_miles, "0");
  $("avgPace").textContent = fmt(summary.recent_avg_run_pace);
  $("avgHr").textContent = fmt(summary.recent_avg_activity_hr || summary.recent_avg_hr);

  renderTrainingMix(summary.recent_training_mix || []);

  const flags = $("recoveryFlags");
  flags.replaceChildren();
  (summary.recovery_flags || []).forEach((flag) => {
    const li = document.createElement("li");
    li.textContent = flag;
    flags.appendChild(li);
  });

  $("projectionText").textContent = `${projection.status}: ${projection.recommendation}`;

  const table = $("activityTable");
  table.replaceChildren();
  const activities = summary.recent_activities || [];
  if (activities.length === 0) {
    table.appendChild(emptyTableRow(
      hasData
        ? "No activities with usable dates in the latest week. Try Refresh after another upload."
        : "Nothing here yet. Upload a Garmin CSV above — sample-data/garmin_activities_sample.csv works for a test run."
    ));
  } else {
    activities.forEach((activity) => table.appendChild(activityRow(activity)));
  }
}

// Disables a button and restores its label when the work finishes,
// so double-clicks can't fire duplicate uploads or coach requests.
async function withBusy(button, busyLabel, work) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    await work();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function handleUpload(event) {
  event.preventDefault();
  const files = Array.from($("garminFile").files);
  if (files.length === 0) {
    setStatus("uploadStatus", "Choose one or more Garmin files first (.csv, .fit, or .zip).", "error");
    return;
  }
  const data = new FormData();
  files.forEach((file) => data.append("files", file));
  await withBusy(event.target.querySelector("button"), "Importing…", async () => {
    setStatus("uploadStatus", files.length === 1 ? "Importing…" : `Importing ${files.length} files…`);
    try {
      const result = await api("/api/upload/garmin", { method: "POST", body: data });
      const failed = (result.files || []).filter((f) => f.status === "error");
      setStatus("uploadStatus", result.message, failed.length ? "" : "ok");
      // Surface per-file errors so one bad file in a batch isn't silent.
      if (failed.length) {
        setStatus("uploadStatus", `${result.message} ${failed.map((f) => f.detail).join(" ")}`, "error");
      }
      event.target.reset();
      await loadDashboard();
    } catch (error) {
      setStatus("uploadStatus", error.message, "error");
    }
  });
}

async function handleProgress(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = {};
  for (const [key, value] of form.entries()) {
    if (value === "") continue;
    payload[key] = key === "notes" || key === "entry_date" ? value : Number(value);
  }
  if (!payload.entry_date) payload.entry_date = toDateInputValue();

  await withBusy(event.target.querySelector("button"), "Saving…", async () => {
    setStatus("acftStatus", "Saving…");
    try {
      const result = await api("/api/progress/entry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("acftStatus", result.message, "ok");
      event.target.reset();
      event.target.entry_date.value = toDateInputValue();
      await loadDashboard();
    } catch (error) {
      setStatus("acftStatus", error.message, "error");
    }
  });
}

async function handleCoach(event) {
  event.preventDefault();
  const question = $("coachQuestion").value.trim();
  if (!question) {
    $("coachAnswer").textContent = "Type a question first — for example: “What should my next three workouts look like?”";
    return;
  }
  await withBusy(event.target.querySelector("button"), "Thinking…", async () => {
    $("coachAnswer").textContent = "Thinking…";
    try {
      const settings = getSavedSettings();
      const headers = new Headers({ "Content-Type": "application/json" });
      if (settings.openaiKey) headers.set("X-OpenAI-API-Key", settings.openaiKey);
      if (settings.openaiModel) headers.set("X-OpenAI-Model", settings.openaiModel);

      const result = await api("/api/coach/ask", {
        method: "POST",
        headers,
        body: JSON.stringify({ question }),
      });
      const sourceNote = result.source === "openai" ? `\n\n— Answered with ${result.model}.` : "";
      $("coachAnswer").textContent = result.answer + sourceNote;
    } catch (error) {
      $("coachAnswer").textContent = error.message;
    }
  });
}

function handleSettings(event) {
  event.preventDefault();
  saveSettingsFromForm();
  setStatus("settingsStatus", "Settings saved in this browser. Refreshing dashboard…", "ok");
  loadDashboard().catch((error) => setStatus("settingsStatus", error.message, "error"));
}

window.addEventListener("DOMContentLoaded", async () => {
  loadSavedSettingsIntoForm();
  $("uploadForm").addEventListener("submit", handleUpload);
  $("acftForm").addEventListener("submit", handleProgress);
  $("coachForm").addEventListener("submit", handleCoach);
  $("settingsForm").addEventListener("submit", handleSettings);
  $("clearSettingsBtn").addEventListener("click", () => {
    clearSavedSettings();
    setStatus("settingsStatus", "Settings cleared from this browser.", "ok");
  });
  $("refreshBtn").addEventListener("click", () => loadDashboard().catch((error) => {
    $("projectionText").textContent = error.message;
  }));
  $("acftForm").entry_date.value = toDateInputValue();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => undefined);
  }

  try {
    await loadDashboard();
  } catch (error) {
    $("projectionText").textContent = error.message;
    $("activityTable").replaceChildren(emptyTableRow(error.message));
  }
});
