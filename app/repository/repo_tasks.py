# app/repository/repo_tasks.py
import sqlite3
from pathlib import Path
import threading
from typing import List, Dict, Any, Optional

# --- 1. 数据库文件路径 (保持不变) ---
DATABASE_FILE = Path(__file__).parent.parent.parent.joinpath("downloader.db")


# --- 2. 数据库连接 (保持不变) ---
def get_db_conn():
    """
    获取一个数据库连接。
    (我们复用这个函数)
    """
    try:
        conn = sqlite3.connect(
            DATABASE_FILE,
            check_same_thread=False,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"[ERROR] 无法连接到 SQLite 数据库: {e}")
        return None


# --- 3. 数据库初始化 (保持不变) ---
def init_db():
    """
    初始化数据库，创建 'tasks' 表 (如果它还不存在)。
    """
    # (我们不再需要锁, FastAPI 的 lifespan 会确保它只运行一次)
    print(f"--- [DATABASE] 正在初始化数据库... {DATABASE_FILE}")

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        custom_name TEXT,
        final_filename TEXT,
        error_message TEXT,
        startTime REAL
    );
    """

    conn = None
    try:
        conn = get_db_conn()
        if conn:
            cursor = conn.cursor()
            cursor.execute(create_table_sql)
            conn.commit()
            print("--- [DATABASE] 数据库和 'tasks' 表已成功初始化。")
    except Exception as e:
        print(f"[ERROR] 无法初始化数据库: {e}")
    finally:
        if conn:
            conn.close()


# --- 【【【V6 核心：CRUD 函数】】】 ---
# 这些函数是 Service 层和数据库之间的唯一接口

def create_task(task_data: Dict[str, Any]) -> None:
    """
    (Create) 向数据库中插入一条新的任务记录
    """
    print(f"--- [REPO] Creating task: {task_data.get('id')}")
    sql = """
    INSERT INTO tasks (id, url, path, status, custom_name, startTime)
    VALUES (:id, :url, :path, :status, :custom_name, :startTime)
    """
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql, task_data)
        conn.commit()
    except Exception as e:
        print(f"[ERROR] [REPO] 无法创建任务: {e}")
    finally:
        if conn:
            conn.close()


def get_all_tasks() -> List[Dict[str, Any]]:
    """
    (Read) 从数据库中获取所有任务
    """
    print("--- [REPO] Getting all tasks")
    sql = "SELECT * FROM tasks ORDER BY startTime DESC"
    tasks = []
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        # conn.row_factory = sqlite3.Row 让我们能将每行转为字典
        for row in cursor.fetchall():
            tasks.append(dict(row))
        return tasks
    except Exception as e:
        print(f"[ERROR] [REPO] 无法获取所有任务: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    """
    (Read) 从数据库中获取单个任务
    """
    print(f"--- [REPO] Getting task: {task_id}")
    sql = "SELECT * FROM tasks WHERE id = ?"
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql, (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[ERROR] [REPO] 无法获取任务 {task_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()


def update_task_status(task_id: str, status: str, error_msg: Optional[str] = None,
                       final_name: Optional[str] = None) -> None:
    """
    (Update) 更新一个任务的状态、错误信息和最终文件名
    """
    print(f"--- [REPO] Updating task {task_id} to status {status}")
    sql = """
    UPDATE tasks
    SET status = :status, error_message = :error_msg, final_filename = :final_name
    WHERE id = :task_id
    """
    params = {
        "status": status,
        "error_msg": error_msg,
        "final_name": final_name,
        "task_id": task_id
    }
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
    except Exception as e:
        print(f"[ERROR] [REPO] 无法更新任务 {task_id}: {e}")
    finally:
        if conn:
            conn.close()


def delete_task(task_id: str) -> None:
    """
    (Delete) 从数据库中删除一条任务记录
    """
    print(f"--- [REPO] Deleting task: {task_id}")
    sql = "DELETE FROM tasks WHERE id = ?"
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql, (task_id,))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] [REPO] 无法删除任务 {task_id}: {e}")
    finally:
        if conn:
            conn.close()