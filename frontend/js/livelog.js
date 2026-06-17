export function renderLiveLogView(container, jobId) {
  container.innerHTML = `
    <p><a href="#/">&larr; back</a></p>
    <h2>Job ${jobId}</h2>
    <div id="terminal"></div>
  `;

  const terminal = container.querySelector("#terminal");
  const source = new EventSource(`/api/jobs/${jobId}/stream`);

  source.onmessage = (e) => {
    appendLine(terminal, e.data);
  };

  source.addEventListener("done", () => {
    source.close();
    window.location.hash = `#/jobs/${jobId}/results`;
  });

  source.onerror = () => {
    appendLine(terminal, "[connection] stream disconnected");
    source.close();
  };
}

function appendLine(terminal, text) {
  const line = document.createElement("div");

  if (text.startsWith("→")) {
    line.className = "log-call";
  } else if (text.startsWith("←")) {
    line.className = "log-result";
  } else if (text.startsWith("[error]") || text.startsWith("[runner] FATAL")) {
    line.className = "log-error";
  } else {
    line.className = "log-info";
  }

  line.textContent = text;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}