const form = document.querySelector("#parse-form");
const urlInput = document.querySelector("#tweet-url");
const statusBox = document.querySelector("#status");
const results = document.querySelector("#results");
const attempts = document.querySelector("#attempts");
const attemptList = document.querySelector("#attempt-list");
const toggleAttempts = document.querySelector("#toggle-attempts");
const choiceList = document.querySelector("#choice-list");
const videoTitle = document.querySelector("#video-title");
const sourceBadge = document.querySelector("#source-badge");

function setStatus(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`.trim();
}

function renderChoices(data) {
  videoTitle.textContent = data.title || "twitter-video";
  sourceBadge.textContent = data.source;
  choiceList.innerHTML = "";

  data.choices.forEach((choice) => {
    const row = document.createElement("article");
    row.className = "choice";

    const meta = document.createElement("div");
    meta.className = "choice-meta";
    meta.innerHTML = `
      <strong>${choice.resolution}</strong>
      <span>${choice.size} · ${choice.ext.toUpperCase()} · ${choice.source}</span>
    `;

    const link = document.createElement("a");
    link.href = choice.download_url;
    link.className = "download";
    link.textContent = "下载";

    row.append(meta, link);
    choiceList.append(row);
  });

  results.hidden = false;
}

function renderAttempts(items) {
  attemptList.innerHTML = "";
  items.forEach((item) => {
    const line = document.createElement("div");
    line.className = `attempt ${item.ok ? "ok" : "fail"}`;
    line.innerHTML = `
      <span>${item.source}</span>
      <strong>${item.ok ? `成功，${item.count} 个格式` : item.error}</strong>
      <em>${item.ms} ms</em>
    `;
    attemptList.append(line);
  });
  attempts.hidden = false;
}

async function parseUrl(url) {
  results.hidden = true;
  attempts.hidden = true;
  attemptList.hidden = true;
  choiceList.innerHTML = "";
  setStatus("正在解析，主源失败会自动切换到备用源...", "loading");

  const response = await fetch("/api/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { message: text };
  }

  if (!response.ok) {
    throw new Error(data.message || data.error || "解析失败");
  }

  renderChoices(data);
  renderAttempts(data.attempts || []);
  setStatus(`找到 ${data.choices.length} 个可下载格式。`, "success");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await parseUrl(urlInput.value.trim());
  } catch (error) {
    setStatus(error.message, "error");
  }
});

toggleAttempts.addEventListener("click", () => {
  attemptList.hidden = !attemptList.hidden;
});

if (urlInput.value.trim()) {
  parseUrl(urlInput.value.trim()).catch((error) => setStatus(error.message, "error"));
}
