const params = new URLSearchParams(window.location.search);
const jobId = params.get("job");
const contentEl = document.getElementById("content");

if (!jobId) {
  renderError("No job id provided in the URL (expected ?job=<id>).");
} else {
  loadResults(jobId);
}

async function loadResults(id) {
  try {
    const res = await fetch(`/api/jobs/${id}`);
    if (!res.ok) throw new Error(`Failed to load job (${res.status})`);
    const job = await res.json();
    renderJob(job);
  } catch (err) {
    renderError(err.message);
  }
}

function renderError(message) {
  contentEl.textContent = "";
  const p = document.createElement("p");
  p.className = "error-text";
  p.textContent = message;
  contentEl.appendChild(p);
}

function renderJob(job) {
  contentEl.textContent = "";

  contentEl.appendChild(buildHeading(job));
  contentEl.appendChild(buildSummaryCard(job));

  const filesHeading = document.createElement("h3");
  filesHeading.textContent = "Files analysed";
  contentEl.appendChild(filesHeading);

  contentEl.appendChild(buildFileList(job.files || []));
}

function buildHeading(job) {
  const h2 = document.createElement("h2");
  h2.textContent = `Job ${job.id}`;
  return h2;
}

function buildSummaryCard(job) {
  const card = document.createElement("div");
  card.className = "summary-card";

  card.appendChild(buildSummaryRow("repo", job.repo_url));

  const statusRow = document.createElement("div");
  statusRow.className = "summary-card__row";
  const statusLabel = document.createElement("span");
  statusLabel.className = "summary-card__label";
  statusLabel.textContent = "status";
  const statusBadge = document.createElement("span");
  statusBadge.className = `badge badge--${job.status}`;
  statusBadge.textContent = job.status;
  statusRow.appendChild(statusLabel);
  statusRow.appendChild(statusBadge);
  card.appendChild(statusRow);

  if (job.summary) {
    const text = document.createElement("p");
    text.className = "summary-card__text";
    text.textContent = job.summary;
    card.appendChild(text);
  }

  if (job.pr_url) {
    const link = document.createElement("a");
    link.className = "pr-link";
    link.href = job.pr_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "View pull request →";
    card.appendChild(link);
  }

  return card;
}

function buildSummaryRow(label, value) {
  const row = document.createElement("div");
  row.className = "summary-card__row";

  const labelEl = document.createElement("span");
  labelEl.className = "summary-card__label";
  labelEl.textContent = label;

  const valueEl = document.createElement("span");
  valueEl.className = "summary-card__value";
  valueEl.textContent = value;

  row.appendChild(labelEl);
  row.appendChild(valueEl);
  return row;
}

function buildFileList(files) {
  const container = document.createElement("div");

  if (files.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No file results recorded for this job.";
    container.appendChild(empty);
    return container;
  }

  for (const file of files) {
    container.appendChild(buildFileCard(file));
  }
  return container;
}

function buildFileCard(file) {
  const card = document.createElement("div");
  card.className = "file-card";

  const path = document.createElement("div");
  path.className = "file-card__path";
  path.textContent = file.path;
  card.appendChild(path);

  const score = file.debt_score;
  const hasScore = typeof score === "number";

  const scoreRow = document.createElement("div");
  scoreRow.className = "file-card__score-row";

  const bar = document.createElement("div");
  bar.className = "debt-bar";
  const fill = document.createElement("div");
  fill.className = `debt-bar__fill ${debtFillClass(score, hasScore)}`;
  fill.style.width = `${hasScore ? score : 0}%`;
  bar.appendChild(fill);

  const scoreLabel = document.createElement("span");
  scoreLabel.className = "file-card__score-label";
  scoreLabel.textContent = hasScore ? `${score}/100` : "not scored";

  scoreRow.appendChild(bar);
  scoreRow.appendChild(scoreLabel);
  card.appendChild(scoreRow);

  if (file.reasons) {
    const reasons = document.createElement("div");
    reasons.className = "file-card__reasons";
    reasons.textContent = file.reasons;
    card.appendChild(reasons);
  }

  if (file.diff) {
    card.appendChild(buildDiffToggle(file.diff));
  }

  return card;
}

function debtFillClass(score, hasScore) {
  if (!hasScore) return "debt-bar__fill--none";
  if (score < 33) return "debt-bar__fill--low";
  if (score < 66) return "debt-bar__fill--mid";
  return "debt-bar__fill--high";
}

function buildDiffToggle(diffText) {
  const details = document.createElement("details");
  details.className = "diff-toggle";

  const summary = document.createElement("summary");
  summary.textContent = "View diff";
  details.appendChild(summary);

  const pre = document.createElement("pre");
  pre.className = "diff";
  pre.textContent = diffText;
  details.appendChild(pre);

  return details;
}