export function renderSubmitView(container) {
  container.innerHTML = `
    <form id="job-form">
      <input
        type="text"
        id="repo-url"
        placeholder="https://github.com/owner/repo"
        required
      />
      <button type="submit" id="submit-btn">Run agent</button>
    </form>
    <p class="error" id="form-error" style="display: none;"></p>

    <h2>Past jobs</h2>
    <ul class="job-list" id="job-list">
      <li>Loading…</li>
    </ul>
  `;

  const form = container.querySelector("#job-form");
  const input = container.querySelector("#repo-url");
  const button = container.querySelector("#submit-btn");
  const errorEl = container.querySelector("#form-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";
    button.disabled = true;
    button.textContent = "Submitting…";

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
      window.location.hash = `#/jobs/${data.job_id}`;
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.style.display = "block";
      button.disabled = false;
      button.textContent = "Run agent";
    }
  });

  loadJobList(container.querySelector("#job-list"));
}

async function loadJobList(listEl) {
  try {
    const res = await fetch("/api/jobs");
    if (!res.ok) throw new Error("Failed to load jobs");
    const jobs = await res.json();

    if (jobs.length === 0) {
      listEl.innerHTML = "<li>No jobs yet.</li>";
      return;
    }

    listEl.innerHTML = jobs
      .map((job) => {
        const link =
          job.status === "complete" || job.status === "failed"
            ? `#/jobs/${job.id}/results`
            : `#/jobs/${job.id}`;
        return `
          <li>
            <a href="${link}">${escapeHtml(job.repo_url)}</a>
            <span class="status status-${job.status}">${job.status}</span>
          </li>
        `;
      })
      .join("");
  } catch (err) {
    listEl.innerHTML = `<li>Could not load past jobs.</li>`;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}