# app/services/service_downloads.py
# (V8.4 - 最终修复版：修复了 get_system_drives 过滤)

import psutil
import uuid
import threading
import subprocess
import queue
import sys
import time
import os
from pathlib import Path
from typing import Dict, Optional, Any, List
import shutil

# 【【V6 核心】】 导入我们的 Repository (数据库) 层
import app.repository.repo_tasks as db 

# 【【V8 核心】】
# 1. 从环境变量中读取下载根目录, 默认为 /downloads
#    (用户将在 docker run -e 中设置这个)
DOWNLOAD_ROOT = Path(os.environ.get("DOWNLOAD_ROOT", "/downloads"))
TEMP_DIR_NAME = ".tmp"

class DownloaderService:
    def __init__(self):
        # 这个字典只存储 *正在运行* 的任务的“实时”对象
        self.live_tasks: Dict[str, dict] = {} 
        # 确保根目录存在
        DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        print(f"--- [SERVICE] DownloaderService V8.4 Singleton created.")
        print(f"--- [SERVICE] 下载根目录 (DOWNLOAD_ROOT): {DOWNLOAD_ROOT}")

    # --- 【【【V8.4 核心修复：更智能的驱动器过滤】】】 ---
    def get_system_drives(self):
        """
        (V8.4) 使用 psutil 获取所有 *真实的、可写的* 挂载点
        """
        print("--- [SERVICE] get_system_drives() (V8.4) called")
        drives = []
        
        # (定义我们不想要的 "虚拟" 文件系统类型)
        FSTYPE_BLACKLIST = [
            'squashfs', # (用于 /rom)
            'tmpfs', 
            'proc', 
            'sysfs', 
            'devtmpfs',
            'cgroup',
            'overlay' # (通常是 /overlay, 我们只想看 *数据* 盘)
        ]
        
        try:
            partitions = psutil.disk_partitions()
            for p in partitions:
                # p.device -> /dev/sda1
                # p.mountpoint -> /mnt/sata1-1
                # p.fstype -> ext4
                # p.opts -> "rw,relatime"
                
                # 【【修复 1】】 过滤掉非 /dev/ 启动的设备 (e.g., /etc/hostname)
                if not p.device.startswith('/dev/'):
                    print(f"--- [SERVICE] Skipping virtual mount: {p.mountpoint}")
                    continue
                    
                # 【【修复 2】】 过滤掉只读 (ro) 硬盘
                if 'ro' in p.opts.split(','):
                    print(f"--- [SERVICE] Skipping read-only drive: {p.mountpoint}")
                    continue
                    
                # 【【修复 3】】 过滤掉虚拟文件系统
                if p.fstype in FSTYPE_BLACKLIST:
                    print(f"--- [SERVICE] Skipping virtual filesystem: {p.fstype} at {p.mountpoint}")
                    continue
                    
                # (通过了所有过滤, 这是一个真实、可写的硬盘)
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    drives.append({
                        "path": p.mountpoint,
                        "fstype": p.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                    })
                except Exception:
                    # (有些挂载点即使可写, 也无法获取 usage)
                    pass
            return drives
        except Exception as e:
            print(f"--- [ERROR] Failed to get system drives: {e}")
            # (V8.4 修复) 返回空列表而不是错误字典，防止 Pydantic 验证失败
            return []

    # --- 【【V8 核心修改：start_new_download】】 ---
    def start_new_download(self, url: str, subdirectory: Optional[str], custom_name: Optional[str]) -> str:
        """
        (V8) 创建任务, *写入数据库*, 并启动后台线程
        """
        
        # 1. 确定最终的下载目录
        if subdirectory:
            # 安全地拼接路径, 防止 ".." 路径遍历
            safe_subdir = Path(subdirectory).name 
            download_dir = DOWNLOAD_ROOT.joinpath(safe_subdir)
        else:
            download_dir = DOWNLOAD_ROOT
        
        print(f"--- [SERVICE] start_new_download() called. Path: {download_dir}")
        
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"--- [ERROR] Failed to create directory {download_dir}: {e}")
            raise e 

        task_id = str(uuid.uuid4())
        log_queue = queue.Queue()
        
        # (V8) 只存储相对路径
        relative_path_str = str(download_dir.relative_to(DOWNLOAD_ROOT))
        # (修复 Windows/Linux 路径分隔符, 统一用 / )
        relative_path_str = relative_path_str.replace('\\', '/')
        if relative_path_str == ".":
            relative_path_str = "" # 根目录

        task_data_to_db = {
            "id": task_id,
            "status": "pending",
            "url": url,
            "path": relative_path_str, # <-- 【V8】只存储 *相对* 路径
            "custom_name": custom_name,
            "startTime": time.time()
        }
        
        self.live_tasks[task_id] = {
            "log_queue": log_queue, "process": None,
        }
        
        try:
            db.create_task(task_data_to_db)
        except Exception as e:
            print(f"[ERROR] [SERVICE] 数据库创建任务失败: {e}")
            del self.live_tasks[task_id]
            raise e
        
        # 【V8】后台线程现在接收 *绝对* 路径
        thread = threading.Thread(target=self._run_download_thread, args=(task_id, download_dir,))
        thread.daemon = True
        thread.start()
        
        print(f"--- [SERVICE] New Task {task_id} started in thread {thread.name}")
        return task_id

    # --- 【【【 V8.3 核心重构：_run_download_thread 】】】 ---
    def _run_download_thread(self, task_id: str, download_dir: Path):
        
        live_task = self.live_tasks.get(task_id)
        db_task = db.get_task_by_id(task_id)
        
        if not live_task or not db_task:
            print(f"--- [ERROR] Thread {task_id}: Task not found in DB or LiveDict.")
            if task_id in self.live_tasks: del self.live_tasks[task_id]
            return

        log_queue = live_task["log_queue"]
        
        def log(message):
            print(f"--- [TASK {task_id}] {message}")
            log_queue.put(message)

        # (V6.3) 定义“工作区”
        tmp_dir = download_dir.joinpath(TEMP_DIR_NAME, task_id)
        
        # (V6.4)
        temp_filename_from_log = None

        try:
            # (V6.3) 创建“工作区”
            tmp_dir.mkdir(parents=True, exist_ok=True)
            log(f"创建临时工作区: {tmp_dir}")
            
            db.update_task_status(task_id, status="downloading")
            log("任务已启动，正在准备下载...")
            
            # (V6.4) 下载到 *隔离区*, 自动命名
            output_template = str(tmp_dir.joinpath("%(title)s.%(ext)s"))

            command = [
                "yt-dlp",
                "--merge-output-format", "mkv",
                "-o", output_template,
                "--progress",
                "--encoding", "utf-8",
                "--ffmpeg-location", "/usr/bin", 
                "--concurrent-fragments", "5",
                db_task["url"]
            ]
            log(f"执行命令: {' '.join(command)}")

            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding='utf-8', errors='replace', bufsize=1,
                universal_newlines=True, startupinfo=startupinfo
            )
            live_task["process"] = process

            # (V8.3 修复：不再解析日志)
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                log(line)
                
                # (V8.4 修复) 我们 *仍然* 需要解析文件名
                if "[download] Destination:" in line:
                    filepath = line.split("Destination: ")[-1]
                    temp_filename_from_log = Path(filepath).name
                elif "[ffmpeg] Merging formats into" in line:
                    task_status_check = db.get_task_by_id(task_id)
                    if task_status_check and task_status_check.get("status") != "merging":
                        db.update_task_status(task_id, status="merging")
                    filepath = line.split('"')[-2]
                    temp_filename_from_log = Path(filepath).name

            process.wait()

            if process.returncode == 0:
                log("下载和合并完成。")
                
                # (V8.3/V6.4 修复：只使用“扫描”逻辑)
                if not temp_filename_from_log:
                    log("警告: 未能从日志中解析出文件名, 正在扫描目录...")
                    found_files = list(tmp_dir.glob("*.mkv")) + list(tmp_dir.glob("*.mp4")) + list(tmp_dir.glob("*.webm"))
                    if not found_files:
                        raise Exception("Download complete but no valid video file (mkv, mp4, webm) found in temp directory.")
                    temp_file_path = found_files[0]
                else:
                    temp_file_path = tmp_dir / temp_filename_from_log
                    if not temp_file_path.exists():
                        log(f"警告: 日志解析的文件 {temp_filename_from_log} 不存在, 正在扫描目录...")
                        found_files = list(tmp_dir.glob("*.mkv")) + list(tmp_dir.glob("*.mp4")) + list(tmp_dir.glob("*.webm"))
                        if not found_files:
                            raise Exception("Download complete but no valid video file found after log parsing failed.")
                        temp_file_path = found_files[0]

                log(f"找到临时文件: {temp_file_path.name}")
                
                downloaded_ext = temp_file_path.suffix.lstrip('.')
                base_name = db_task["custom_name"] or temp_file_path.stem
                
                resolved_base_filename = self._resolve_filename(
                    download_dir,
                    base_name, 
                    downloaded_ext
                )
                final_filename_with_ext = f"{resolved_base_filename}.{downloaded_ext}"
                final_file_path = download_dir / final_filename_with_ext
                
                log(f"正在移动文件到: {final_file_path}")
                os.rename(temp_file_path, final_file_path)
                
                db.update_task_status(
                    task_id, 
                    status="complete", 
                    final_name=final_filename_with_ext
                )
            else:
                if process.returncode == -15:
                    raise Exception("任务被用户取消。")
                else:
                    raise Exception(f"yt-dlp 进程以错误码 {process.returncode} 退出。")

        except Exception as e:
            log(f"!!! 任务失败 !!!")
            log(str(e))
            db.update_task_status(
                task_id, 
                status="error", 
                error_msg=str(e)
            )
            
        finally:
            log_queue.put(None)
            if task_id in self.live_tasks:
                del self.live_tasks[task_id]
            
            try:
                if tmp_dir.exists():
                    log(f"正在清理临时工作区: {tmp_dir}")
                    shutil.rmtree(tmp_dir)
            except Exception as e_clean:
                log(f"清理临时工作区失败: {e_clean}")
            
            log(f"--- 任务 {task_id} 线程结束 ---")

    # --- (_resolve_filename 保持不变) ---
    def _resolve_filename(self, path: Path, base_name: str, ext: str) -> str:
        final_path = path / f"{base_name}.{ext}"
        counter = 1
        original_name = base_name
        while os.path.exists(final_path):
            counter += 1
            base_name = f"{original_name} ({counter})"
            final_path = path / f"{base_name}.{ext}"
        return base_name

    # --- (get_download_stream 保持不变) ---
    def get_download_stream(self, task_id: str):
        live_task = self.live_tasks.get(task_id)
        if not live_task:
            def error_generator():
                yield "data: [ERROR] Task not found in live memory (already finished?).\n\n"
                yield "data: [STREAM_END]\n\n"
            return error_generator()
        log_queue = live_task["log_queue"]
        def stream_generator():
            print(f"--- [SSE] Stream opened for task {task_id}")
            while True:
                line = log_queue.get() 
                if line is None:
                    print(f"--- [SSE] Stream closing for task {task_id}")
                    yield "data: [STREAM_END]\n\n"
                    break
                yield f"data: {line}\n\n"
        return stream_generator()

    # --- 【【V8.4 修复】】 ---
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        print(f"--- [SERVICE] get_all_tasks() called")
        try:
            return db.get_all_tasks() or []
        except Exception as e:
            print(f"[ERROR] [SERVICE] 无法从数据库获取任务: {e}")
            return [] # 即使数据库失败也返回空列表

    # --- (get_task_status 保持不变) ---
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        print(f"--- [SERVICE] get_task_status() called for task: {task_id}")
        return db.get_task_by_id(task_id)

    # --- 【【V8 核心修改：delete_file_from_server】】 ---
    def delete_file_from_server(self, file_path_relative: str) -> dict:
        """
        (V8) 从服务器删除一个 *相对* 路径的文件
        """
        print(f"--- [SERVICE] delete_file_from_server() called. Path: {file_path_relative}")
        
        try:
            # 【V8 安全】
            file_to_delete = DOWNLOAD_ROOT.joinpath(file_path_relative).resolve()
            
            if DOWNLOAD_ROOT not in file_to_delete.parents:
                 return {"success": False, "message": "Invalid path (Path Traversal)."}
                 
            if file_to_delete.is_file():
                file_to_delete.unlink()
                return {"success": True, "message": f"Deleted {file_to_delete}"}
            else:
                return {"success": False, "message": "File not found or is a directory"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # --- (cancel_running_task 保持不变) ---
    def cancel_running_task(self, task_id: str) -> dict:
        print(f"--- [SERVICE] Attempting to cancel task {task_id}")
        if task_id not in self.live_tasks:
            return {"success": False, "message": "Task is not running or already finished."}
        live_task = self.live_tasks[task_id]
        process = live_task.get("process")
        if process:
            print(f"--- [SERVICE] Terminating process {process.pid} for task {task_id}")
            try:
                process.terminate()
                return {"success": True}
            except Exception as e:
                print(f"--- [ERROR] Failed to terminate process for {task_id}: {e}")
                return {"success": False, "message": str(e)}
        else:
            return {"success": False, "message": "Task is pending but has no process yet."}

    # --- (delete_task 保持不变) ---
    def delete_task(self, task_id: str) -> dict:
        print(f"--- [SERVICE] Deleting task {task_id} from DB and memory")
        if task_id in self.live_tasks:
            live_task = self.live_tasks[task_id]
            process = live_task.get("process")
            if process:
                print(f"--- [SERVICE] Task {task_id} is running, attempting to terminate...")
                try:
                    process.terminate()
                except Exception as e:
                    print(f"--- [ERROR] Failed to terminate process for {task_id}: {e}")
            del self.live_tasks[task_id]
        try:
            db.delete_task(task_id)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"DB delete failed: {e}"}

# --- 【【核心：创建单例】】 (保持不变) ---
downloader_service = DownloaderService()

