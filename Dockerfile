# 1. 使用一个轻量级的 Python 3.10 基础镜像
FROM python:3.10-slim

# 2. 安装系统依赖
# (项目需要 ffmpeg 来处理视频)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. 设置容器内的工作目录
WORKDIR /app

# 4. 复制依赖文件
# (先复制这一个文件是为了利用 Docker 的构建缓存)
COPY requirements.txt .

# 5. 安装 Python 依赖
# (使用你指定的清华源来加速)
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 6. 复制项目的所有文件到工作目录
COPY . .

# 7. 声明数据卷
# (该项目会将下载的文件和日志保存在 ./data 目录，我们将其声明为卷)
VOLUME /app/data

# 8. 暴露端口
# (根据 config.py，Web 服务默认运行在 5000 端口)
EXPOSE 5000

# 9. 容器启动时运行的命令
# (启动 run.py，它会以 0.0.0.0:5000 运行)
CMD ["python", "run.py"]
