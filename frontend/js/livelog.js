const params = new URLSearchParams(window.location.search);
const jobId = params.get("job");

const titleEl = document.getElementById("job-title");
const idLineEl = document.getElementById("job-id-line");
const connectionLineEl = document.getElementById("connection-line");
const terminalBody = document.getElementById("terminal-body");

if (!jobId) {
  setConnectionState("No job id provided in the URL (expected ?job=<id>).", "lost");
} else {
  idLineEl.textContent = jobId;
  connectStream(jobId);
}

function connectStream(id) {
  const source = new EventSource(`/api/jobs/${id}/stream`);

  source.onopen = () => {
    setConnectionState("Connected — streaming live output.", "connected");
  };

  source.onmessage = (e) => {
    appendLine(e.data);
  };

  source.addEventListener("done", () => {
    setConnectionState("Job finished. Redirecting to results…", "connected");
    source.close();
    window.location.href = `results.html?job=${id}`;
  });

  source.onerror = () => {
    setConnectionState("Connection lost — the browser will retry automatically.", "lost");
  };
}

function setConnectionState(message, state) {
  connectionLineEl.textContent = message;
  connectionLineEl.className = "connection-line";
  if (state === "connected") {
    connectionLineEl.classList.add("connection-line--connected");
  } else if (state === "lost") {
    connectionLineEl.classList.add("connection-line--lost");
  }
}

function classifyLine(text) {
  if (text.startsWith("→")) return "log-line--call";
  if (text.startsWith("←")) return "log-line--result";
  if (text.startsWith("[error]") || text.startsWith("[runner] FATAL")) return "log-line--error";
  if (text.startsWith("[loop] step")) return "log-line--step";
  return "log-line--info";
}

function appendLine(text) {
  const line = document.createElement("div");
  line.className = `log-line ${classifyLine(text)}`;
  line.textContent = text;
  terminalBody.appendChild(line);
  terminalBody.scrollTop = terminalBody.scrollHeight;
}