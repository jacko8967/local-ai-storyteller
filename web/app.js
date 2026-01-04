function getSessionId() {
  let sid = localStorage.getItem("story_session_id");
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem("story_session_id", sid);
  }
  return sid;
}

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
    lastMatchIndex = match.index + (match[1] ? match[1].length : 0); // adjust if newline captured
  }

  let mainText = t;
  let choicesText = "";

  if (lastMatchIndex >= 0) {
    mainText = t.slice(0, lastMatchIndex).trimEnd();
    choicesText = t.slice(lastMatchIndex).trim();
  }

  // Show transcript (everything except the latest choices block)
  const transcriptDiv = document.createElement("div");
  transcriptDiv.textContent = mainText || "No story yet. Click 'New Story' to begin.";
  container.appendChild(transcriptDiv);

  // Render ONLY the latest choices as buttons
  if (choicesText) {
    const choicesDiv = document.createElement("div");
    choicesDiv.style.marginTop = "14px";

    const lines = choicesText.split("\n").map(l => l.trim()).filter(Boolean);
    const choiceLines = lines.filter(l => /^[1-3]\.\s+/.test(l)).slice(0, 3);

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
        // send the choice text as the action
        actionEl.value = m[2];
        sendAction();
      };

      choicesDiv.appendChild(btn);
    });

    container.appendChild(choicesDiv);
  }

  storyEl.appendChild(container);

  // Scroll to bottom
  container.scrollTop = container.scrollHeight;
}


async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
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

async function loadStory() {
  // Fetch current story state (or start if missing)
  const data = await api("/api/story/get", { session_id: sessionId });
  storyEl.textContent = data.story || "No story yet. Click 'New Story' to begin.";
}

async function newStory() {
  sendBtn.disabled = true;
  newBtn.disabled = true;
  storyEl.textContent = "Starting a new story…";
  const data = await api("/api/story/new", { session_id: sessionId });
  renderStory(data.story);
  sendBtn.disabled = false;
  newBtn.disabled = false;
}

async function sendAction() {
  const action = actionEl.value.trim();
  if (!action) return;

  sendBtn.disabled = true;
  newBtn.disabled = true;

  storyEl.textContent += `\n\n> You: ${action}\n\n(Thinking…)`;
  actionEl.value = "";

  try {
    const data = await api("/api/story/turn", { session_id: sessionId, action });
    renderStory(data.story);
  } catch (err) {
    storyEl.textContent += `\n\n[Error]\n${err.message}`;
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
