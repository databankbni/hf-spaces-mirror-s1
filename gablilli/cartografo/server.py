import asyncio
import os
import subprocess
import json
from pathlib import Path
from fastapi import FastAPI, Response, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

BASE = Path("/app")
MARTIN_PORT = 3001
martin_process = None

@app.on_event("startup")
async def start_martin():
    global martin_process
    pmtiles_path = BASE / "italy.pmtiles"
    if pmtiles_path.exists():
        martin_process = subprocess.Popen([
            "martin",
            "--listen-addresses", f"127.0.0.1:{MARTIN_PORT}",
            str(pmtiles_path)
        ])
        await asyncio.sleep(2)
        print(f"Martin avviato su porta {MARTIN_PORT}")
    else:
        print("ATTENZIONE: italy.pmtiles non trovato")

@app.on_event("shutdown")
async def stop_martin():
    if martin_process:
        martin_process.terminate()

@app.get("/style.json")
async def get_style():
    with open(BASE / "style.json") as f:
        style = json.load(f)
    return Response(
        content=json.dumps(style),
        media_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"}
    )

@app.get("/tiles/italy")
async def tilejson():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{MARTIN_PORT}/italy")
        data = r.json()
        data["tiles"] = ["https://cartografo.insidegubbio.com/tiles/italy/{z}/{x}/{y}"]
        return Response(
            content=json.dumps(data),
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )

@app.get("/tiles/{path:path}")
async def proxy_tiles(path: str):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"http://127.0.0.1:{MARTIN_PORT}/{path}")
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "application/x-protobuf"),
                headers={"Access-Control-Allow-Origin": "*"}
            )
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))
        
@app.get("/italy.pmtiles")
async def serve_pmtiles(request: Request):
    pmtiles_path = BASE / "italy.pmtiles"
    if not pmtiles_path.exists():
        raise HTTPException(status_code=404, detail="Tiles not ready")
    
    file_size = pmtiles_path.stat().st_size
    range_header = request.headers.get("Range")
    
    if range_header:
        range_val = range_header.replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0])
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1
        
        with open(pmtiles_path, "rb") as f:
            f.seek(start)
            chunk = f.read(length)
        
        return Response(
            content=chunk,
            status_code=206,
            media_type="application/octet-stream",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
            }
        )
    else:
        return Response(
            content=b"",
            status_code=200,
            media_type="application/octet-stream",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
            }
        )

@app.get("/fonts/{fontstack}/{range}.pbf")
async def get_font(fontstack: str, range: str):
    font_path = BASE / "fonts" / fontstack / f"{range}.pbf"
    if not font_path.exists():
        font_path = BASE / "fonts" / "noto-sans" / f"{range}.pbf"
    if not font_path.exists():
        raise HTTPException(status_code=404, detail=f"Font not found: {fontstack}/{range}")
    return Response(
        content=font_path.read_bytes(),
        media_type="application/x-protobuf",
        headers={"Access-Control-Allow-Origin": "*"}
    )

@app.get("/sprites/{filename}")
async def get_sprite(filename: str):
    sprite_path = BASE / "sprites" / filename
    if not sprite_path.exists():
        raise HTTPException(status_code=404, detail=f"Sprite not found: {filename}")
    media_type = "application/json" if filename.endswith(".json") else "image/png"
    return Response(
        content=sprite_path.read_bytes(),
        media_type=media_type,
        headers={"Access-Control-Allow-Origin": "*"}
    )

@app.get("/health")
async def health():
    pmtiles_exists = (BASE / "italy.pmtiles").exists()
    return {
        "status": "ok",
        "tiles": "ready" if pmtiles_exists else "downloading",
        "martin": "running" if martin_process and martin_process.poll() is None else "stopped"
    }

@app.get("/")
async def root():
    return {
        "name": "Cartografo - insidegubbio Map Server",
        "endpoints": {
            "style": "/style.json",
            "tiles": "/tiles/...",
            "fonts": "/fonts/{fontstack}/{range}.pbf",
            "sprites": "/sprites/sprite.json",
            "health": "/health"
        }
    }
