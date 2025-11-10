# Dockerfile

# 1. 基础：从一个“空白的”、已安装 Python 3.10 的 Linux (Debian) 开始
FROM python:3.10-slim

# 2. 【系统依赖】
# 在这个“空白”系统上安装 ffmpeg/ffprobe。
# (这等同于我们在 OpenWrt 上运行 opkg install ffmpeg)
# (sqlite3 已经包含在 python:3.10-slim 中了)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. 设置工作目录
WORKDIR /app

# 4. 【Python 依赖】
# 复制 "requirements.txt"
COPY requirements.txt .

# 运行 pip install
# (在 Debian 容器内, pip install psutil/pycryptodomex 会 100% 成功)
RUN pip install --no-cache-dir -r requirements.txt

# 5. 【复制代码】
# 复制你的 *所有* 代码 (app/, dist/, run.py) 到容器的 /app 目录
COPY . .

# 6. 【启动命令】
# (运行我们已修改为 5001 端口的 run.py)
CMD ["python", "run.py"]