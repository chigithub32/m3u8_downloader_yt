# app/main.py
# (V8 - “干净”的 venv 兼容版)

import os
import sys # (我们不再需要 sys.path.insert)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path 

# --- 【【【V8 核心：只计算 dist 路径】】】 ---
APP_FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = APP_FILE_PATH.parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
DIST_ASSETS_DIR = DIST_DIR / "assets"
INDEX_HTML_FILE = DIST_DIR / "index.html"
# --- 【【【修复结束】】】 ---

# 4. 导入我们的模块 (现在 venv 会自动处理路径)
from app.repository.repo_tasks import init_db
from app.api.v1 import router_downloads
from fastapi.middleware.cors import CORSMiddleware

# ... (lifespan, app = FastAPI(...), CORS... 保持不变) ...

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("--- [APP] 应用正在启动...")
    print(f"--- [APP] Project Root: {PROJECT_ROOT}")
    print(f"--- [APP] Dist Dir: {DIST_DIR}")
    init_db()
    yield
    print("--- [APP] 应用正在关闭...")

app = FastAPI(title="M3U8 Downloader API (V8)", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router_downloads.router)

# 9. 托管 Vue 前端 (使用绝对路径)
app.mount("/assets", StaticFiles(directory=str(DIST_ASSETS_DIR)), name="assets")
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_vue_app(full_path: str):
    index_path = str(INDEX_HTML_FILE)
    if not os.path.exists(index_path):
        return {"error": f"'dist/index.html' not found at {index_path}"}, 404
    return FileResponse(index_path)