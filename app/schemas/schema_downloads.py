# app/schemas/schema_downloads.py
from pydantic import BaseModel, Field
from typing import List, Optional

# Field(...) 意味着这个字段是必需的
# Optional[str] = None 意味着这个字段是可选的

# -----------------------------------------------
# (A) 用于 API 请求 (Request)
# -----------------------------------------------

class DownloadRequest(BaseModel):
    """
    对应 Spring Boot 的 @RequestBody
    这是 POST /api/v1/start-download 接收的 JSON
    """
    url: str
    download_path: str = Field(..., description="用户提供的绝对路径...")

    # --- 【【【核心修复：添加这一行】】】 ---
    custom_filename: Optional[str] = Field(None, description="用户自定义的文件名 (不含扩展名)")
    # --- 【【【修复结束】】】 ---

class FileDeleteRequest(BaseModel):
    """
    这是 DELETE /api/v1/file 接收的 JSON
    """
    file_path: str = Field(..., description="要删除的文件的绝对路径")


# -----------------------------------------------
# (B) 用于 API 响应 (Response)
# -----------------------------------------------

class DriveResponse(BaseModel):
    """
    这是 GET /api/v1/system/drives 返回的列表项
    """
    path: str
    fstype: str
    total_gb: float
    free_gb: float

class TaskStatusResponse(BaseModel):
    """
    这是 GET /api/v1/tasks 和 GET /api/v1/status/{id} 返回的对象
    """
    id: str
    status: str
    url: str
    path: str
    log: Optional[str] = None
    progress: float = 0
    final_filename: Optional[str] = None
    error_message: Optional[str] = None
    startTime: Optional[float] = None # 我们用它来排序

    class Config:
        # Pydantic 默认只处理字典, an_object.id
        # orm_mode = True (在新版中叫 from_attributes=True)
        # 允许 Pydantic 从对象属性中读取数据
        # (这在我们将 Service 层的字典转为 Pydantic 模型时很有用)
        orm_mode = True

class TaskIdResponse(BaseModel):
    """
    这是 POST /api/v1/start-download 的标准返回
    """
    taskId: str