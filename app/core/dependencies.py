# app/core/dependencies.py
from app.services.service_downloads import DownloaderService, downloader_service


def get_downloader_service() -> DownloaderService:
    """
    依赖注入 (DI) "提供者"。

    当 FastAPI 在路由函数中看到 Depends(get_downloader_service) 时,
    它会调用这个函数, 而这个函数只是简单地返回我们已经创建好的
    *单例* 'downloader_service' 实例。

    这就像 Spring 的 @Autowired。
    """
    return downloader_service