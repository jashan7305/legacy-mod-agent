const form = document.getElementById("job-form");
const input = document.getElementById("repo-url");
const button = document.getElementById("submit-btn");
const errorEl = document.getElementById("form-error");
const tableBody = document.getElementById("job-table-body");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError();
  setSubmitting(true);

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: input.value.trim() }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }

    const data = await res.json();
    window.location.href = `livelog.html?job=${data.job_id}`;
  } catch (err) {
    showError(err.message);
    setSubmitting(false);
  }
});

function setSubmitting(isSubmitting) {
  button.disabled = isSubmitting;
  button.textContent = isSubmitting ? "Submitting…" : "Run agent";
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.style.display = "block";
}

function hideError() {
  errorEl.style.display = "none";
}

async function loadJobList() {
  clearTable();

  try {
    const res = await fetch("/api/jobs");
    if (!res.ok) throw new Error("Failed to load jobs");
    const jobs = await res.json();

    if (jobs.length === 0) {
      appendEmptyRow("No jobs yet — submit a repo above to get started.");
      return;
    }

    for (const job of jobs) {
      tableBody.appendChild(buildJobRow(job));
    }
  } catch (err) {
    appendEmptyRow("Could not load past jobs.");
  }
}

function clearTable() {
  tableBody.textContent = "";
}

function appendEmptyRow(message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.className = "job-table__empty";
  cell.textContent = message;
  row.appendChild(cell);
  tableBody.appendChild(row);
}

function buildJobRow(job) {
  const row = document.createElement("tr");
  row.className = "job-table__row";

  const repoCell = document.createElement("td");
  repoCell.className = "job-table__cell job-table__cell--repo";

  const link = document.createElement("a");
  const targetPage =
    job.status === "complete" || job.status === "failed"
      ? "results.html"
      : "livelog.html";
  link.href = `${targetPage}?job=${job.id}`;
  link.textContent = job.repo_url;
  repoCell.appendChild(link);

  const statusCell = document.createElement("td");
  statusCell.className = "job-table__cell job-table__cell--status";
  statusCell.appendChild(buildStatusBadge(job.status));

  row.appendChild(repoCell);
  row.appendChild(statusCell);
  return row;
}

function buildStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `badge badge--${status}`;
  badge.textContent = status;
  return badge;
}

loadJobList();