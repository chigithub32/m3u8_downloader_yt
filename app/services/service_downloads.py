# app/services/service_downloads.py
# (V6.4 - 最终修复版：智能查找下载的文件类型)

import psutil, uuid, threading, subprocess, queue, sys, time, os
from pathlib import Path
from typing import Dict, Optional, Any, List
import shutil

import app.repository.repo_tasks as db

TEMP_DIR_NAME = ".tmp"


class DownloaderService:
    def __init__(self):
        self.live_tasks: Dict[str, dict] = {}
        print("--- [SERVICE] DownloaderService V6.4 Singleton created.")

    # --- (get_system_drives 保持不变) ---
    def get_system_drives(self):
        print("--- [SERVICE] get_system_drives() called")
        drives = []
        try:
            partitions = psutil.disk_partitions()
            for p in partitions:
                if p.fstype and p.opts.find('ro') == -1:
                    try:
                        usage = psutil.disk_usage(p.mountpoint)
                        drives.append({
                            "path": p.mountpoint, "fstype": p.fstype,
                            "total_gb": round(usage.total / (1024 ** 3), 2),
                            "free_gb": round(usage.free / (1024 ** 3), 2),
                        })
                    except Exception:
                        pass
            return drives
        except Exception as e:
            print(f"--- [ERROR] Failed to get system drives: {e}")
            return {"error": str(e)}

    # --- (start_new_download 保持不变) ---
    def start_new_download(self, url: str, download_path: str, custom_name: Optional[str]) -> str:
        print(f"--- [SERVICE] start_new_download() called. Path: {download_path}")
        try:
            download_dir = Path(download_path)
            download_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"--- [ERROR] Failed to create directory {download_path}: {e}")
            raise e
        task_id = str(uuid.uuid4())
        log_queue = queue.Queue()
        task_data_to_db = {
            "id": task_id, "status": "pending", "url": url,
            "path": str(download_dir), "custom_name": custom_name,
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
        thread = threading.Thread(target=self._run_download_thread, args=(task_id,))
        thread.daemon = True
        thread.start()
        print(f"--- [SERVICE] New Task {task_id} started in thread {thread.name}")
        return task_id

    # --- 【【【 V6.4 核心重构：_run_download_thread 】】】 ---
    def _run_download_thread(self, task_id: str):

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
        download_dir = Path(db_task["path"])
        tmp_dir = download_dir.joinpath(TEMP_DIR_NAME, task_id)

        # (V6.4) 我们需要一个变量来存储下载时的真实文件名
        temp_filename_from_log = None

        try:
            # (V6.3) 创建“工作区”
            tmp_dir.mkdir(parents=True, exist_ok=True)
            log(f"创建临时工作区: {tmp_dir}")

            db.update_task_status(task_id, status="downloading")
            log("任务已启动，正在准备下载...")

            # (V6.3) 我们 *仍然* 使用 yt-dlp 的自动命名 (%(title)s)，但下载到 *隔离区*
            # 【注意】我们不再在文件名中添加 [task_id]，因为文件夹已经是唯一的了
            output_template = str(tmp_dir.joinpath("%(title)s.%(ext)s"))

            command = [
                "yt-dlp",
                "--merge-output-format", "mkv",  # (如果需要合并, 则合并为 mkv)
                "-o", output_template,  # (下载到 .../.tmp/[task_id]/...)
                "--progress",
                "--encoding", "utf-8",
                "--concurrent-fragments", "5",
                db_task["url"]
            ]
            log(f"执行命令: {' '.join(command)}")

            # (Popen 逻辑保持不变)
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

            for line in process.stdout:
                line = line.strip()
                if not line: continue
                log(line)

                # (V6.4) 实时捕获 yt-dlp 告知的 *最终* 文件名
                if "[download] Destination:" in line:
                    filepath = line.split("Destination: ")[-1]
                    temp_filename_from_log = Path(filepath).name
                elif "[ffmpeg] Merging formats into" in line:
                    task_status = db.get_task_by_id(task_id)["status"]
                    if task_status != "merging":
                        db.update_task_status(task_id, status="merging")
                    filepath = line.split('"')[-2]
                    temp_filename_from_log = Path(filepath).name

            process.wait()

            # --- 【【V6.4 核心：成功处理】】 ---
            if process.returncode == 0:
                log("下载和合并完成。")

                # 7a. 【【V6.4 修复】】
                # 我们不再猜测扩展名 (glob)，我们使用从日志中捕获的文件名
                if not temp_filename_from_log:
                    # (备用方案：如果日志解析失败, 我们在 tmp_dir 中 *盲目* 查找)
                    log("警告: 未能从日志中解析出文件名, 正在扫描目录...")
                    found_files = list(tmp_dir.glob("*.mkv")) + list(tmp_dir.glob("*.mp4")) + list(
                        tmp_dir.glob("*.webm"))
                    if not found_files:
                        raise Exception(
                            "Download complete but no valid video file (mkv, mp4, webm) found in temp directory.")
                    temp_file_path = found_files[0]
                else:
                    temp_file_path = tmp_dir / temp_filename_from_log

                log(f"找到临时文件: {temp_file_path.name}")

                # 7b. 确定最终文件名
                downloaded_ext = temp_file_path.suffix.lstrip('.')  # e.g., "mkv" or "mp4"
                base_name = db_task["custom_name"] or temp_file_path.stem  # (用自定义名称, 或用下载到的文件名(不含扩展名))

                resolved_base_filename = self._resolve_filename(
                    download_dir,  # 目标是 *父* 目录
                    base_name,
                    downloaded_ext  # <-- 使用 *实际* 的扩展名
                )
                final_filename_with_ext = f"{resolved_base_filename}.{downloaded_ext}"
                final_file_path = download_dir / final_filename_with_ext

                # 7c. 移动文件
                log(f"正在移动文件到: {final_file_path}")
                os.rename(temp_file_path, final_file_path)

                # 7d. 更新数据库
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
            # (V6.3 清理逻辑保持不变)
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

    # --- (get_all_tasks 保持不变) ---
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        print(f"--- [SERVICE] get_all_tasks() called")
        return db.get_all_tasks()

    # --- (get_task_status 保持不变) ---
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        print(f"--- [SERVICE] get_task_status() called for task: {task_id}")
        return db.get_task_by_id(task_id)

    # --- (delete_file_from_server 保持不变) ---
    def delete_file_from_server(self, file_path: str) -> dict:
        print(f"--- [SERVICE] delete_file_from_server() called. Path: {file_path}")
        if not file_path or ".." in file_path:
            return {"success": False, "message": "Invalid path."}
        try:
            file_to_delete = Path(file_path)
            if file_to_delete.is_file():
                file_to_delete.unlink()
                return {"success": True, "message": f"Deleted {file_path}"}
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