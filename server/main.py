from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os

app = FastAPI(title="Crypto PR+ Mini App Server")

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
web_dir = os.path.join(root_dir, "webapp")

app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

@app.get("/api/health")
def health():
    return JSONResponse({"ok": True})
