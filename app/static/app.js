const $ = (id) => document.getElementById(id);

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

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Can't reach the app. Is the server still running?");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error("This server requires a token (APP_SECRET_TOKEN is set). The web dashboard is meant for open local use — clear the token in .env, or call the API with an Authorization header.");
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
  td.colSpan = 7;
  td.className = "empty-row";
  td.textContent = message;
  row.appendChild(td);
  return row;
}

async function loadDashboard() {
  const [summary, projection] = await Promise.all([
    api("/api/summary/latest"),
    api("/api/training/projection"),
  ]);

  const hasData = (summary.activity_count_total || 0) > 0;

  $("twoMileMarker").textContent = fmt(summary.current_two_mile_marker, hasData ? "—" : "No data yet");
  $("goalText").textContent = `Goal: ${fmt(summary.goal_two_mile)}`;
  $("recentRuns").textContent = fmt(summary.recent_runs, "0");
  $("recentMiles").textContent = fmt(summary.recent_run_miles, "0");
  $("avgPace").textContent = fmt(summary.recent_avg_run_pace);
  $("avgHr").textContent = fmt(summary.recent_avg_hr);

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
  const file = $("garminFile").files[0];
  if (!file) {
    setStatus("uploadStatus", "Choose a Garmin CSV file first.", "error");
    return;
  }
  const data = new FormData();
  data.append("file", file);
  await withBusy(event.target.querySelector("button"), "Importing…", async () => {
    setStatus("uploadStatus", "Importing…");
    try {
      const result = await api("/api/upload/garmin-csv", { method: "POST", body: data });
      setStatus("uploadStatus", result.message, "ok");
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
      const result = await api("/api/coach/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      $("coachAnswer").textContent = result.answer;
    } catch (error) {
      $("coachAnswer").textContent = error.message;
    }
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  $("uploadForm").addEventListener("submit", handleUpload);
  $("acftForm").addEventListener("submit", handleProgress);
  $("coachForm").addEventListener("submit", handleCoach);
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
