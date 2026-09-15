"""FastAPI 入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import SessionLocal, init_db
from .deps import get_current_user
from .middleware import CacheHeadersMiddleware, UserContextMiddleware
from .routers import auth, meals, misc, notify, settings, tokens, users
from .services.notify import Scheduler

_scheduler = Scheduler(SessionLocal)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()  # 建表 + 标签字典 + 初始管理员，幂等
    try:
        from .services.sounds import ensure_presets
        ensure_presets()  # 预设提醒音效（合成 WAV）
    except Exception as _e:  # noqa: BLE001
        print(f"[sounds] 预设音效生成失败：{_e}", flush=True)
    if config.ENABLE_SCHEDULER:
        _scheduler.start()  # 通知定时任务（后台线程）
    yield
    _scheduler.stop()


app = FastAPI(title="今天吃得怎么样 · AI 饮食观察日记", version="0.7.1",
              description="拍照识别 → 人工确认 → 时间线/图表 → 自然语言查库 → 阶段总结",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 压缩 JSON / JS / CSS（服务器上行带宽小时尤其重要；若前面有 Caddy 也会再压一次，无害）
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CacheHeadersMiddleware)
app.add_middleware(UserContextMiddleware)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}


# 认证路由自身不需要登录；其余业务路由统一要求登录
app.include_router(auth.router)
protected = [Depends(get_current_user)]
app.include_router(meals.router, dependencies=protected)
app.include_router(misc.router, dependencies=protected)
app.include_router(settings.router, dependencies=protected)
app.include_router(notify.router, dependencies=protected)
app.include_router(tokens.router)   # 自带 get_current_user
app.include_router(users.router)    # 自带 require_admin

# v0.3 功能模块：存在即加载（各模块自行在 router 上声明鉴权依赖）
import importlib  # noqa: E402

for _mod in ("health", "memory", "data", "barcode", "share", "mcp_server", "usage", "sounds"):
    try:
        _m = importlib.import_module(f"app.routers.{_mod}")
    except ModuleNotFoundError as _e:
        if _e.name and _e.name.endswith(_mod):
            continue  # 模块尚不存在
        raise
    app.include_router(_m.router)


@app.get("/uploads/thumb/{name}", include_in_schema=False, dependencies=protected)
def serve_thumb(name: str):
    """缩略图（320px）；没有缩略图时回退原图。"""
    if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise HTTPException(status_code=404)
    thumb = Path(config.UPLOAD_DIR) / "thumb" / name
    if thumb.is_file():
        return FileResponse(str(thumb))
    full = Path(config.UPLOAD_DIR) / name
    if full.is_file():
        return FileResponse(str(full))
    raise HTTPException(status_code=404)


@app.get("/uploads/{path:path}", include_in_schema=False, dependencies=protected)
def serve_upload(path: str):
    """上传文件（含 dish_images/、share/ 等子目录）属于私人数据，需登录才能访问；同时防止路径穿越。

    注意：早期版本只支持单层文件名，导致 /uploads/dish_images/x.jpg、/uploads/share/x.png
    全部 404（餐单图片、历史分享卡片图片无法显示）。此处改为支持多级子路径。
    """
    if not path or path.startswith(".") or "\\" in path or ".." in path:
        raise HTTPException(status_code=404)
    base = Path(config.UPLOAD_DIR).resolve()
    target = (base / path).resolve()
    # 必须落在 uploads 目录内，杜绝 ../ 穿越
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(target))


# 若前端已构建（frontend/dist），由后端一并托管，实现单进程演示
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    _DIST_RESOLVED = _DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # 只允许返回 dist 目录内的文件，防止 ../ 路径穿越读取到 backend/.env 等
        target = (_DIST / full_path).resolve()
        # is_relative_to 同时兼容 Linux 的 / 与 Windows 的 \ 分隔符
        if full_path and target.is_file() and target != _DIST_RESOLVED and target.is_relative_to(_DIST_RESOLVED):
            return FileResponse(str(target))
        return FileResponse(str(_DIST / "index.html"))
