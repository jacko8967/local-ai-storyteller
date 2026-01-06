function getSessionId() {
  let sid = localStorage.getItem("story_session_id");
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem("story_session_id", sid);
  }
  return sid;
}

function extractErrorMessage(text) {
  try {
    const obj = JSON.parse(text);
    if (obj && typeof obj.detail === "string") return obj.detail;
    if (obj && typeof obj.message === "string") return obj.message;
  } catch (e) {
    // not JSON
  }
  return (text || "").trim() || "Request failed.";
}

/* ============================
   Streaming typewriter control
   ============================ */
const STREAM_MS_PER_CHAR = 14; // lower=faster, higher=slower (try 12–20)
let streamQueue = "";
let streamTimer = null;
let streamRendered = ""; // <-- NEW: accumulates what's been shown so far
let pendingFinalStory = null;
let pendingFinalizeFn = null;

function startTypewriter(prefix, onUpdate) {
  // reset state for a new stream
  streamRendered = "";

  if (streamTimer) clearInterval(streamTimer);

  streamTimer = setInterval(() => {
  if (!streamQueue) {
    // If stream is done and we were waiting to finalize, do it now
    if (pendingFinalizeFn) {
      const fn = pendingFinalizeFn;
      pendingFinalizeFn = null;
      fn();
    }
    return;
  }

  const take = Math.max(1, Math.floor(30 / STREAM_MS_PER_CHAR));
  const chunk = streamQueue.slice(0, take);
  streamQueue = streamQueue.slice(take);

  streamRendered += chunk;
  onUpdate(prefix + streamRendered);

  // If we just drained the last chunk and we're waiting to finalize, finalize now
  if (!streamQueue && pendingFinalizeFn) {
    const fn = pendingFinalizeFn;
    pendingFinalizeFn = null;
    fn();
  }
}, STREAM_MS_PER_CHAR);
}

function stopTypewriter() {
  if (streamTimer) clearInterval(streamTimer);
  streamTimer = null;
  streamQueue = "";
  streamRendered = ""; // <-- reset
}

/* ============================ */

let currentStoryText = "";

function renderStory(text) {
  storyEl.innerHTML = "";

  const container = document.createElement("div");
  container.style.whiteSpace = "pre-wrap";
  container.style.border = "1px solid #ddd";
  container.style.padding = "12px";
  container.style.borderRadius = "8px";
  container.style.minHeight = "200px";
  container.style.maxHeight = "500px";
  container.style.overflowY = "auto";

  const t = (text || "").trim();

  // Find the LAST occurrence of a "1. " line (start of latest choice block)
  const re = /(^|\n)1\.\s+/g;
  let lastMatchIndex = -1;
  let match;
  while ((match = re.exec(t)) !== null) {
    lastMatchIndex = match.index + (match[1] ? match[1].length : 0);
  }

  let mainText = t;
  let choicesText = "";

  if (lastMatchIndex >= 0) {
    mainText = t.slice(0, lastMatchIndex).trimEnd();
    choicesText = t.slice(lastMatchIndex).trim();
  }

  const transcriptDiv = document.createElement("div");
  transcriptDiv.textContent =
    mainText || "No story yet. Click 'New Story' to begin.";
  container.appendChild(transcriptDiv);

  if (choicesText) {
    const choicesDiv = document.createElement("div");
    choicesDiv.style.marginTop = "14px";

    const lines = choicesText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);

    const choiceLines = lines
      .filter((l) => /^[1-3]\.\s+/.test(l))
      .slice(0, 3);

    choiceLines.forEach((line) => {
      const m = line.match(/^([1-3])\.\s+(.*)$/);
      if (!m) return;

      const btn = document.createElement("button");
      btn.textContent = line;
      btn.style.display = "block";
      btn.style.marginTop = "6px";
      btn.style.padding = "10px 12px";
      btn.style.borderRadius = "8px";
      btn.style.border = "1px solid #ccc";
      btn.style.cursor = "pointer";
      btn.style.textAlign = "left";
      btn.style.width = "100%";

      btn.onclick = () => {
        actionEl.value = m[2];
        sendAction();
      };

      choicesDiv.appendChild(btn);
    });

    container.appendChild(choicesDiv);
  }

  storyEl.appendChild(container);
  container.scrollTop = container.scrollHeight;
}

function renderStoryProgress(text) {
  storyEl.innerHTML = "";
  const box = document.createElement("div");
  box.style.whiteSpace = "pre-wrap";
  box.style.border = "1px solid #ddd";
  box.style.padding = "12px";
  box.style.borderRadius = "8px";
  box.style.minHeight = "200px";
  box.textContent = text;
  storyEl.appendChild(box);
  box.scrollTop = box.scrollHeight;
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(extractErrorMessage(text));
  }
  return res.json();
}

const storyEl = document.getElementById("story");
const actionEl = document.getElementById("action");
const sendBtn = document.getElementById("send");
const newBtn = document.getElementById("new");
const metaEl = document.getElementById("meta");

const sessionId = getSessionId();
metaEl.textContent = `Session: ${sessionId}`;

async function streamNdjson(path, body, onEvent) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
  const text = await res.text();
  throw new Error(extractErrorMessage(text));
  }

  if (!res.body) {
  throw new Error("No response body (stream unavailable).");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);

      if (!line) continue;
      try {
        const evt = JSON.parse(line);
        onEvent(evt);
      } catch (e) {
      // Ignore malformed lines
    }
  }
  }
}

async function loadStory() {
  const data = await api("/api/story/get", { session_id: sessionId });
  currentStoryText = data.story || "";
  renderStory(currentStoryText);

  
}

async function newStory() {
  sendBtn.disabled = true;
  newBtn.disabled = true;

  renderStoryProgress("Starting a new story…");

  try {
    await streamNdjson(
      "/api/story/new_stream",
      { session_id: sessionId },
      (evt) => {
        if (evt.type === "chunk") {
          streamQueue += evt.text;
          if (!streamTimer) {
            startTypewriter("", (text) => renderStoryProgress(text));
          }
        } else if (evt.type === "final") {
          pendingFinalStory = evt.story || "";
          pendingFinalizeFn = () => {
            stopTypewriter();
            currentStoryText = pendingFinalStory || "";
            renderStory(currentStoryText);
          };

          if (!streamQueue) {
            const fn = pendingFinalizeFn;
            pendingFinalizeFn = null;
            fn();
          }
        } else if (evt.type === "error") {
          // backend streamed error
          stopTypewriter();
          streamQueue = "";
          pendingFinalStory = null;
          pendingFinalizeFn = null;
          renderStoryProgress("[Error]\n" + (evt.message || "Unknown error."));
        }
      }
    );
  } catch (err) {
    // fetch failed or non-200 (e.g. 503 when Ollama is down)
    stopTypewriter();
    streamQueue = "";
    pendingFinalStory = null;
    pendingFinalizeFn = null;
    renderStoryProgress("[Error]\n" + (err?.message || String(err)));
  } finally {
    sendBtn.disabled = false;
    newBtn.disabled = false;
    actionEl.focus();
  }
}

async function sendAction() {
  const action = actionEl.value.trim();
  if (!action) return;

  sendBtn.disabled = true;
  newBtn.disabled = true;
  actionEl.value = "";

  const prefix =
    (currentStoryText ? currentStoryText.trim() + "\n\n" : "") +
    `> You: ${action}\n\n`;

  renderStoryProgress(prefix + "(Thinking…)\n");

  try {
    await streamNdjson(
      "/api/story/turn_stream",
      { session_id: sessionId, action },
      (evt) => {
        if (evt.type === "chunk") {
          streamQueue += evt.text;
          if (!streamTimer) {
            startTypewriter(prefix, (text) => renderStoryProgress(text));
          }
        } else if (evt.type === "final") {
          pendingFinalStory = evt.story || "";
          pendingFinalizeFn = () => {
            stopTypewriter();
            currentStoryText = pendingFinalStory || "";
            renderStory(currentStoryText);
          };

          if (!streamQueue) {
            const fn = pendingFinalizeFn;
            pendingFinalizeFn = null;
            fn();
          }
        } else if (evt.type === "error") {
          stopTypewriter();
          streamQueue = "";
          pendingFinalStory = null;
          pendingFinalizeFn = null;
          renderStoryProgress(prefix + "\n[Error]\n" + (evt.message || "Unknown error."));
        }
      }
    );
  } catch (err) {
    stopTypewriter();
    streamQueue = "";
    pendingFinalStory = null;
    pendingFinalizeFn = null;
    renderStoryProgress(prefix + "\n[Error]\n" + (err?.message || String(err)));
  } finally {
    sendBtn.disabled = false;
    newBtn.disabled = false;
    actionEl.focus();
  }
}


sendBtn.addEventListener("click", sendAction);
newBtn.addEventListener("click", newStory);
actionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendAction();
});

loadStory();
