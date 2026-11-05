from __future__ import annotations

import argparse
import io
import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.paths import ROOT, configure_environment, inside
from backend.app.chat import Chat, MODEL, api_key
from backend.app.store import Store, read_json, settings
from backend.app.tools import KnowledgeTools

_store: Store | None = None
chat = Chat()

def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_environment()
    get_store()
    yield

app = FastAPI(title="Meridian", lifespan=lifespan)

class ChatInput(BaseModel):
    message: str
    session_id: str | None = None

class ReviewInput(BaseModel):
    action: str
    value: Any = None
    note: str = ""

@app.exception_handler(KeyError)
async def key_error(request, exc):
    return Response(json.dumps({"detail": str(exc).strip("'")}), status_code=404, media_type="application/json")

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return Response(json.dumps({"detail": str(exc)}), status_code=400, media_type="application/json")

@app.get("/api/status")
def status():
    store = get_store()
    return {"chat_available": bool(api_key()), "chat_model": MODEL, "revision": store.revision,
            "parts": len(store.records), "drawings": sum(bool(p.get("drawing")) for p in store.records),
            "models": sum(bool(p.get("has_3d")) for p in store.records), "reviewer_name": settings().get("reviewer_name", "Jason Peng")}

@app.get("/api/parts")
def parts(q: str = "", section: str = "", material: str = "", view: str = "", review: str = ""):
    store = get_store()
    tools = KnowledgeTools(store)
    records = store.records
    if q:
        keys = {p["key"] for p in tools.find_part(q)["parts"]}
        records = [p for p in records if p["key"] in keys or q.casefold() in str(p).casefold()]
    if section:
        records = [p for p in records if p.get("section", "").casefold() == section.casefold()]
    if material:
        keys = {p["key"] for p in tools.parts_with_material(material)["parts"]}
        records = [p for p in records if p["key"] in keys]
    if view:
        records = [p for p in records if ("3d" if p.get("has_3d") else "2d" if p.get("has_drawing") else "bom") == view]
    if review:
        records = [p for p in records if p.get("review_status") == review]
    return [{**tools.summary(p), "material": (tools.material(p) or {}).get("display"), "weight_check": p.get("weight_check"),
             "drawing": {"id": p["drawing"]["id"], "image": p["drawing"].get("image"), "degraded": p["drawing"].get("degraded")} if p.get("drawing") else None} for p in records]

def drawing_image(key: str, page: int = 1):
    part = get_store().part(unquote(key))
    drawing = part.get("drawing")
    if not drawing:
        raise HTTPException(404, "This part has no drawing")
    if page < 1 or page > drawing.get("pages", 1):
        raise HTTPException(404, "Drawing page not found")
    image_path = drawing.get("images", [])[page - 1] if drawing.get("images") else f"images/{drawing['id']}-p{page}.png"
    path = inside(get_store().generated / image_path)
    if not path.is_file():
        raise HTTPException(404, "Drawing image not generated")
    return part, drawing, path

@app.get("/api/parts/{key:path}/image")
def image(key: str, page: int = 1, thumb: int = 0):
    _, _, path = drawing_image(key, page)
    if thumb:
        from PIL import Image
        im = Image.open(path)
        im.thumbnail((400, 280))
        buffer = io.BytesIO()
        im.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")
    return FileResponse(path, media_type="image/png")

@app.get("/api/parts/{key:path}/crop")
def crop(key: str, fact: str):
    store = get_store()
    field = store.fields.get(fact)
    if not field or store.owners.get(fact) is not store.part(unquote(key)):
        raise HTTPException(404, "Fact is not evidence for this part")
    if not field.get("box"):
        source = next((store.fields[n] for n in field.get("fact_ids", []) if n in store.fields and store.fields[n].get("box")), None)
        if source:
            field = source
    if not field.get("box"):
        raise HTTPException(404, "This fact has no drawing region")
    page = field.get("page", 1)
    _, drawing, path = drawing_image(key, page)
    from PIL import Image
    im = Image.open(path)
    w, h = drawing["page_sizes"][page - 1]
    x, y, bw, bh = field["box"]
    pad = 12
    box = (max(0, (x-pad)*im.width/w), max(0, (y-pad)*im.height/h), min(im.width, (x+bw+pad)*im.width/w), min(im.height, (y+bh+pad)*im.height/h))
    im = im.crop(tuple(round(v) for v in box))
    buffer = io.BytesIO()
    im.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")

@app.get("/api/parts/{key:path}/history")
def history(key: str, fact: str | None = None):
    return get_store().history(unquote(key), fact)

@app.get("/api/parts/{key:path}")
def part(key: str):
    store = get_store()
    record = store.part(unquote(key))
    facts = KnowledgeTools(store).get_facts(record["key"])["facts"]
    pending = [item for item in store.review_items() if item.get("part_key") == record["key"] and item.get("status") in {"pending", "not_reviewed"}]
    return {**record, "facts": facts, "review_items": pending,
            "waiting": [item["target"] for item in pending if item["type"] in {"template", "link", "source_changed"}], "revision": store.revision}

@app.get("/api/models/{filename}")
def model(filename: str):
    if not (filename.endswith(".glb") or filename.endswith(".step")) or "/" in filename or "\\" in filename:
        raise HTTPException(404)
    path = inside(get_store().generated / "models" / filename)
    if not path.is_file():
        # STEP download routes accept the short API name as well as the honest filename.
        if filename.endswith(".step"):
            path = inside(get_store().generated / "models" / filename.replace(".step", "_reconstruction_from_drawing.step"))
        if not path.is_file():
            raise HTTPException(404, "Model artifact is unavailable")
    return FileResponse(path, media_type="model/gltf-binary" if filename.endswith(".glb") else "application/step", filename=path.name if filename.endswith(".step") else None)

@app.get("/api/review")
def review():
    return get_store().review_items()

@app.post("/api/review/{item_id:path}")
def review_action(item_id: str, body: ReviewInput):
    return get_store().act(unquote(item_id), body.action, body.value, body.note)

@app.get("/api/accuracy")
def accuracy():
    return get_store().accuracy()

@app.get("/api/readme")
def readme():
    return read_json(get_store().generated / "readme.json", [])

@app.post("/api/chat")
async def answer(body: ChatInput):
    if not body.message.strip():
        raise HTTPException(400, "Enter a question")
    try:
        return await chat.answer(get_store(), body.message, body.session_id)
    except (ValueError, KeyError):
        raise
    except Exception as exc:
        # Avoid exposing authentication headers or provider request contents.
        name = type(exc).__name__
        raise HTTPException(502, f"Chat provider error ({name}). Check credentials and model access.") from None

@app.get("/generated/{relative:path}")
def generated_asset(relative: str):
    path = inside(get_store().generated / relative)
    if not path.is_relative_to(get_store().generated) or path.suffix not in {".png", ".glb", ".step"} or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)

@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    dist = ROOT / "frontend" / "dist"
    candidate = inside(dist / path)
    if candidate.is_relative_to(dist) and candidate.is_file():
        return FileResponse(candidate)
    if (dist / "index.html").exists():
        return FileResponse(dist / "index.html")
    return Response("Meridian frontend is not built. Run npm --prefix frontend run build.", status_code=503)

def cli():
    configure_environment()
    parser = argparse.ArgumentParser(description="Meridian local evidence workbench")
    parser.add_argument("command", nargs="?", choices=["serve", "rebuild", "prep", "models"], default="serve")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "prep":
        from backend.loader import build_records
        from backend.ai.pipeline import run_prep
        build_records()
        run_prep()
        build_records()
        return
    if args.command == "models":
        get_store().rebuild_models()
        return
    if args.command == "rebuild":
        get_store().reload(rebuild=True)
        get_store().rebuild_models()
        print("Rebuilt records; preserved and replayed decisions.")
        return
    # Normal use loads the shipped evidence/assets; explicit rebuild is the
    # regeneration path. A missing cache still restores offline on first use.
    get_store()
    if not (ROOT / "generated/models/manifest.json").exists():
        get_store().rebuild_models()
    print("Meridian: http://127.0.0.1:" + str(args.port))
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)

if __name__ == "__main__":
    cli()
