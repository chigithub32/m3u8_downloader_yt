# run.py
import uvicorn

if __name__ == "__main__":
    print("--- [RUNNER] 正在启动 Uvicorn 服务器...")
    # 'app.main:app' 告诉 uvicorn:
    # 1. 去 "app" 包里
    # 2. 找到 "main.py" 文件
    # 3. 加载名为 "app" 的 FastAPI 实例
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5001,
        reload=True  # (开发时开启热重载, 生产环境应设为 False)
    )