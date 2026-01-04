from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
import httpx

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ----------------------------
# Simple in-memory session store
# ----------------------------
# sessions[session_id] = {
#   "history": [{"role": "system"/"user"/"assistant", "content": "..."}],
#   "story_text": "..."
# }
sessions: dict[str, dict] = {}


# ----------------------------
# Models
# ----------------------------
class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"


class StoryGetRequest(BaseModel):
    session_id: str


class StoryNewRequest(BaseModel):
    session_id: str


class StoryTurnRequest(BaseModel):
    session_id: str
    action: str


# ----------------------------
# Basic routes
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


# ----------------------------
# Ollama helper
# ----------------------------
async def call_ollama(prompt: str, model: str) -> str:
    ollama_url = "http://localhost:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(ollama_url, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("response", "")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama at {ollama_url}: {str(e)}")


# ----------------------------
# Existing simple generate API (still handy)
# ----------------------------
@app.post("/api/generate")
async def generate(req: GenerateRequest):
    text = await call_ollama(req.prompt, req.model)
    return {"text": text}


# ----------------------------
# Story system prompt (you can tweak later)
# ----------------------------
SYSTEM_PROMPT = """
You are a narrative game master for an interactive story.
Write vivid, coherent story text in 2nd person present tense.
Keep each response 120-220 words.
Always end with exactly 3 numbered choices (1, 2, 3), each 8-14 words.
Do not mention you are an AI. Do not break character.
"""


def build_prompt(history: list[dict]) -> str:
    """
    Turn a role/content history into a single prompt string for /api/generate.
    (Simple approach for now; later we can switch to chat format.)
    """
    out = []
    for msg in history:
        role = msg["role"]
        content = msg["content"].strip()
        if role == "system":
            out.append(content)
        elif role == "user":
            out.append(f"\nUser: {content}")
        elif role == "assistant":
            out.append(f"\nAssistant: {content}")
    out.append("\nAssistant:")
    return "\n".join(out).strip()


# ----------------------------
# Story endpoints
# ----------------------------
def build_transcript(history: list[dict]) -> str:
    parts = []
    for msg in history:
        role = msg["role"]
        content = msg["content"].strip()
        if role == "system":
            continue
        if role == "user":
            parts.append(f"> You: {content}")
        elif role == "assistant":
            parts.append(content)
    return "\n\n".join(parts).strip()

@app.post("/api/story/get")
async def story_get(req: StoryGetRequest):
    session = sessions.get(req.session_id)
    if not session:
        return {"story": ""}
    return {"story": build_transcript(session["history"])}


@app.post("/api/story/new")
async def story_new(req: StoryNewRequest):
    # Initialize session
    history = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": "Start a new dark fantasy adventure with a strong hook."},
    ]

    prompt = build_prompt(history)
    story = await call_ollama(prompt, model="gemma3:latest")

    history.append({"role": "assistant", "content": story})

    sessions[req.session_id] = {
        "history": history,
        "story_text": story,
    }

    return {"story": build_transcript(history)}



@app.post("/api/story/turn")
async def story_turn(req: StoryTurnRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found. Click 'New Story' first.")

    history = session["history"]

    # Add the player's action
    history.append({"role": "user", "content": req.action})

    # Build prompt + generate
    prompt = build_prompt(history)
    story = await call_ollama(prompt, model="gemma3:latest")

    # Save assistant reply
    history.append({"role": "assistant", "content": story})
    session["story_text"] = story

    return {"story": build_transcript(history)}
