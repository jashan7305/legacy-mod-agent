export async function renderResultsView(container, jobId) {
  container.innerHTML = `<p>Loading results…</p>`;

  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new Error(`Failed to load job (${res.status})`);
    const job = await res.json();

    container.innerHTML = `
      <p><a href="#/">&larr; back</a></p>
      <h2>Job ${job.id}</h2>

      <div class="summary-box">
        <p><strong>Repo:</strong> ${escapeHtml(job.repo_url)}</p>
        <p><strong>Status:</strong>
          <span class="status status-${job.status}">${job.status}</span>
        </p>
        ${job.summary ? `<p>${escapeHtml(job.summary)}</p>` : ""}
        ${
          job.pr_url
            ? `<a class="pr-link" href="${job.pr_url}" target="_blank" rel="noopener">View pull request</a>`
            : ""
        }
      </div>

      <h3>Files analysed</h3>
      <ul class="file-list" id="file-list"></ul>
    `;

    renderFileList(container.querySelector("#file-list"), job.files || []);
  } catch (err) {
    container.innerHTML = `
      <p><a href="#/">&larr; back</a></p>
      <p class="error">${escapeHtml(err.message)}</p>
    `;
  }
}

function renderFileList(listEl, files) {
  if (files.length === 0) {
    listEl.innerHTML = "<li>No file results recorded.</li>";
    return;
  }

  listEl.innerHTML = files
    .map((file) => {
      const score = file.debt_score;
      const hasScore = typeof score === "number";
      const barColor = hasScore ? debtColor(score) : "#ccc";
      const barWidth = hasScore ? score : 0;

      return `
        <li>
          <div>${escapeHtml(file.path)}</div>
          <div class="debt-bar">
            <div class="debt-bar-fill" style="width:${barWidth}%; background:${barColor};"></div>
          </div>
          ${hasScore ? `<div>Debt score: ${score}/100</div>` : `<div>Debt score: not scored</div>`}
          ${
            file.diff
              ? `<details><summary>View diff</summary><pre class="diff">${escapeHtml(file.diff)}</pre></details>`
              : ""
          }
        </li>
      `;
    })
    .join("");
}

function debtColor(score) {
  if (score < 33) return "#2ecc71";
  if (score < 66) return "#f1c40f";
  return "#e74c3c";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}