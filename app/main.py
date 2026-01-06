from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.db import init_db, save_session, load_session

import json
import copy
import httpx

app = FastAPI()

# Initialize DB on startup
@app.on_event("startup")
def _startup():
    init_db()


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


DEFAULT_STATE = {
    "location": "starting_area",
    "inventory": [],
    "flags": {},
    "relationships": {},
}


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
OLLAMA_BASE_URL = "http://localhost:11434"

async def ensure_ollama_ready():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start Ollama and try again."
        )


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

async def stream_ollama(prompt: str, model: str):
    """
    Yields incremental text chunks from Ollama (/api/generate with stream=True).
    Ollama returns JSON lines like: {"response":"...", "done":false}
    """
    ollama_url = "http://localhost:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", ollama_url, json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("response"):
                        yield data["response"]

                    if data.get("done") is True:
                        break

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


def format_state(state: dict) -> str:
    inv = state.get("inventory", [])
    flags = state.get("flags", {})
    rel = state.get("relationships", {})

    inv_txt = ", ".join(inv) if inv else "(empty)"
    flags_txt = ", ".join([f"{k}={v}" for k, v in flags.items()]) if flags else "(none)"
    rel_txt = ", ".join([f"{k}:{v}" for k, v in rel.items()]) if rel else "(none)"

    return (
        "WORLD STATE (authoritative)\n"
        f"- inventory: {inv_txt}\n"
        f"- flags: {flags_txt}\n"
        f"- relationships: {rel_txt}\n"
    )


def build_prompt(history: list[dict], state: dict) -> str:
    """
    Turn a role/content history into a single prompt string for /api/generate.
    (Simple approach for now; later we can switch to chat format.)
    """
    out = []
    injected_state = False

    for msg in history:
        role = msg["role"]
        content = msg["content"].strip()

        if role == "system":
            out.append(content)
            if not injected_state:
                out.append("\n" + format_state(state).strip())
                injected_state = True

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

    # If not in memory, try DB
    if not session:
        db_row = load_session(req.session_id)
        if not db_row:
            return {"story": ""}

        sessions[req.session_id] = {
            "history": db_row["history"],
            "story_text": db_row.get("story_text", ""),
            "state": db_row.get("state") or copy.deepcopy(DEFAULT_STATE),
        }
        session = sessions[req.session_id]

    return {"story": build_transcript(session["history"])}


@app.post("/api/story/new")
async def story_new(req: StoryNewRequest):
    await ensure_ollama_ready()
    # Initialize session
    history = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": "Start a new dark fantasy adventure with a strong hook."},
    ]
    
    # Initialize state ONCE
    state = copy.deepcopy(DEFAULT_STATE)

    # Build prompt + generate
    prompt = build_prompt(history, state)
    story = await call_ollama(prompt, model="gemma3:latest")

    # Save assistant reply
    history.append({"role": "assistant", "content": story})
    
    # Save to in-memory and DB
    sessions[req.session_id] = {
        "history": history,
        "story_text": story,
        "state": state,
    }

    save_session(req.session_id, history, story, state)

    return {"story": build_transcript(history)}


@app.post("/api/story/turn")
async def story_turn(req: StoryTurnRequest):
    await ensure_ollama_ready()
    # Retrieve session
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found. Click 'New Story' first.")

    # Ensure state exists
    session.setdefault("state", copy.deepcopy(DEFAULT_STATE))
    
    history = session["history"]
    history.append({"role": "user", "content": req.action})

    # Build prompt + generate
    prompt = build_prompt(history, session["state"])
    story = await call_ollama(prompt, model="gemma3:latest")

    # Save assistant reply
    history.append({"role": "assistant", "content": story})
    session["story_text"] = story

    save_session(req.session_id, history, story, session["state"])

    return {"story": build_transcript(history)}


@app.post("/api/story/new_stream")
async def story_new_stream(req: StoryNewRequest):
    await ensure_ollama_ready()
    history = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": "Start a new dark fantasy adventure with a strong hook."},
    ]
    
    state = copy.deepcopy(DEFAULT_STATE)

    prompt = build_prompt(history, state)

    async def ndjson_gen():
        assistant_text = ""
        try:
            async for chunk in stream_ollama(prompt, model="gemma3:latest"):
                assistant_text += chunk
                yield json.dumps({"type": "chunk", "text": chunk}) + "\n"

            history.append({"role": "assistant", "content": assistant_text})
            sessions[req.session_id] = {
                "history": history,
                "story_text": assistant_text,
                "state": state,
            }

            save_session(req.session_id, history, assistant_text, state)

            final_story = build_transcript(history)
            yield json.dumps({"type": "final", "story": final_story}) + "\n"

        except Exception as e:
            yield json.dumps({
                "type": "error",
                "message": "Ollama is not running. Start it and try again."
            }) + "\n"

    return StreamingResponse(ndjson_gen(), media_type="application/x-ndjson")


@app.post("/api/story/turn_stream")
async def story_turn_stream(req: StoryTurnRequest):
    await ensure_ollama_ready()
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found. Click 'New Story' first.")
    
    session.setdefault("state", copy.deepcopy(DEFAULT_STATE))

    history = session["history"]
    prompt = build_prompt(history, session["state"])
    
    history.append({"role": "user", "content": req.action})
    prompt = build_prompt(history, session["state"])

    async def ndjson_gen():
        assistant_text = ""
        try:
            async for chunk in stream_ollama(prompt, model="gemma3:latest"):
                assistant_text += chunk
                yield json.dumps({"type": "chunk", "text": chunk}) + "\n"

            history.append({"role": "assistant", "content": assistant_text})
            session["story_text"] = assistant_text

            save_session(req.session_id, history, assistant_text, session["state"])

            final_story = build_transcript(history)
            yield json.dumps({"type": "final", "story": final_story}) + "\n"

        except Exception:
            yield json.dumps({
                "type": "error",
                "message": "Ollama is not running. Start it and try again."
            }) + "\n"

    return StreamingResponse(ndjson_gen(), media_type="application/x-ndjson")