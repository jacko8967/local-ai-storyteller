function getSessionId() {
  let sid = localStorage.getItem("story_session_id");
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem("story_session_id", sid);
  }
  return sid;
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
  storyEl.textContent = data.story;
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
    storyEl.textContent = data.story;
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
