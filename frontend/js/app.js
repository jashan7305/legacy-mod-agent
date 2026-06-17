import { renderSubmitView } from "./submit.js";
import { renderLiveLogView } from "./livelog.js";
import { renderResultsView } from "./results.js";

const app = document.getElementById("app");

function route() {
  const hash = window.location.hash || "#/";
  const jobMatch = hash.match(/^#\/jobs\/([a-zA-Z0-9-]+)$/);
  const resultsMatch = hash.match(/^#\/jobs\/([a-zA-Z0-9-]+)\/results$/);

  app.innerHTML = "";

  if (resultsMatch) {
    renderResultsView(app, resultsMatch[1]);
  } else if (jobMatch) {
    renderLiveLogView(app, jobMatch[1]);
  } else {
    renderSubmitView(app);
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);

// in case the script loads after DOMContentLoaded already fired
if (document.readyState !== "loading") {
  route();
}