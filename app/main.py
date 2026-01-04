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


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    ollama_url = "http://localhost:11434/api/generate"
    payload = {
        "model": req.model,
        "prompt": req.prompt,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(ollama_url, json=payload)
            r.raise_for_status()
            data = r.json()
            return {"text": data.get("response", "")}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama at {ollama_url}: {str(e)}")
