# app/api/v1/router_downloads.py
# (V6 - Controller 层)

from fastapi import APIRouter, Depends, Path as FastPath, HTTPException, Response
from starlette.responses import StreamingResponse
from typing import Dict, List, Any

# 1. 导入 Service 和 DI
from app.services.service_downloads import DownloaderService
from app.core.dependencies import get_downloader_service

# 2. 导入 Schemas (DTOs)
from app.schemas.schema_downloads import (
    DownloadRequest,
    FileDeleteRequest,
    TaskStatusResponse,
    DriveResponse,
    TaskIdResponse
)

# 3. 创建一个 APIRouter (就像 Flask 的 Blueprint)
# 这就是你的 "DownloadController"
router = APIRouter(
    prefix="/api/v1",  # 所有路由都带 /api/v1 前缀
    tags=["Downloads"] # 在 Swagger 文档中分组
)

# --- 定义 API 路由 ---

# (A) 系统接口
@router.get("/system/drives", response_model=List[DriveResponse])
def get_drives(service: DownloaderService = Depends(get_downloader_service)):
    """
    获取服务器所有挂载的驱动器
    (FastAPI 会自动把 service.get_system_drives() 返回的 list[dict] 转换成 list[DriveResponse])
    """
    return service.get_system_drives()

# (B) 核心下载流程
@router.post("/start-download", response_model=TaskIdResponse)
def start_download(
    req: DownloadRequest, # <-- FastAPI 自动使用 Pydantic 模型验证请求体
    service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6) 启动一个新下载, 包含自定义文件名
    """
    try:
        task_id = service.start_new_download(
            req.url,
            req.download_path,
            req.custom_filename # <-- 【V6 新增】 传递自定义文件名
        )
        return TaskIdResponse(taskId=task_id)
    except Exception as e:
        # 如果创建目录失败或数据库写入失败
        print(f"[ERROR] [API] 启动下载失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动任务失败: {e}")

@router.get("/stream-progress/{task_id}")
def stream_progress(
    task_id: str = FastPath(..., description="任务 ID"),
    service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6) 实时获取下载进度 (SSE)
    """
    stream_generator = service.get_download_stream(task_id)
    return StreamingResponse(
        stream_generator,
        media_type="text/event-stream"
    )

# (C) 任务与文件管理
@router.get("/tasks", response_model=List[TaskStatusResponse])
def get_tasks(service: DownloaderService = Depends(get_downloader_service)):
    """
    (V6) 从 *数据库* 获取所有任务的列表
    """
    # service.get_all_tasks() 返回一个 list[dict]
    # "response_model=List[TaskStatusResponse]" 会自动将其转换为 JSON 列表
    # (注意：Pydantic v1.x 使用 'response_model_by_alias=False' 会更好)
    tasks_list = service.get_all_tasks()
    return tasks_list

@router.get("/status/{task_id}", response_model=TaskStatusResponse)
def get_status(
    task_id: str = FastPath(..., description="任务 ID"),
    service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6) 从 *数据库* 获取单个任务的最终状态
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found in database")
    return task

@router.delete("/task/{task_id}")
def delete_task(
    task_id: str = FastPath(..., description="要从列表清除的任务 ID"),
    service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6) 从 *数据库* 和 *内存* 中删除一个任务记录 (修复 Bug 1 & 2)
    """
    result = service.delete_task(task_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return Response(status_code=204) # 204 No Content 是 DELETE 成功的标准返回

@router.delete("/file")
def delete_file(
    req: FileDeleteRequest, # <-- FastAPI 自动验证请求体
    service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6) 从服务器磁盘上删除一个 *物理文件*
    """
    result = service.delete_file_from_server(req.file_path)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("message", "File not found"))
    return Response(status_code=204) # 204 No Content


# (这是粘贴在 router_downloads.py 中的新路由)

@router.post("/task/{task_id}/cancel", status_code=202)
def cancel_task(
        task_id: str = FastPath(..., description="要取消的正在运行的任务 ID"),
        service: DownloaderService = Depends(get_downloader_service)
):
    """
    (V6.1 新增) 请求取消一个正在运行的下载任务。

    这会终止 yt-dlp 进程。
    该任务随后会自动失败 (status='error') 并被移入历史记录。
    """
    result = service.cancel_running_task(task_id)
    if not result["success"]:
        # 404 Not Found 或 409 Conflict 可能更合适, 但 404 易于处理
        raise HTTPException(status_code=404, detail=result.get("message"))

    return {"message": "Task cancellation requested."}