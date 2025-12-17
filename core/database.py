import sqlite3
import threading
import json
import os
import logging
from enum import IntEnum
from datetime import datetime, timedelta

logger = logging.getLogger("DB")

class TaskStatus(IntEnum):
    PENDING = 0
    DONE = 1
    RETRY = 2

class TaskQueueDB:
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = str(db_path)
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row 
        return conn

    def _init_db(self):
        with self.lock:
            conn = self._get_conn()
            try:
                with conn: 
                    conn.execute(f'''
                        CREATE TABLE IF NOT EXISTS tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,               -- 任务ID
                            action TEXT,                                        -- 操作类型：UPLOAD / DELETE             
                            local_path TEXT,                                    -- 本地文件绝对路径
                            rel_path TEXT,                                      -- 相对路径（上传到服务器后的路径）    
                            extra_data TEXT,                                    -- 额外数据（JSON格式）
                            status INTEGER DEFAULT {TaskStatus.PENDING},        -- 任务状态
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- 创建时间
                            next_retry_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 核心：退避时间字段
                            retry_count INTEGER DEFAULT 0                       -- 重试次数
                        )
                    ''')
                    # 索引优化：加快 get_pending_task 的速度
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_status_time ON tasks (status, next_retry_at)")
            finally:
                conn.close()

    def add_task(self, action, local_path, rel_path, extra_data=None):
        with self.lock:
            conn = self._get_conn()
            try:
                with conn:
                    if action == 'UPLOAD':
                        cursor = conn.execute(
                            "SELECT id FROM tasks WHERE local_path=? AND status=? AND action='UPLOAD'", 
                            (str(local_path), TaskStatus.PENDING)
                        )
                        if cursor.fetchone(): return None

                    conn.execute(
                        "INSERT INTO tasks (action, local_path, rel_path, extra_data) VALUES (?, ?, ?, ?)",
                        (action, str(local_path), rel_path, json.dumps(extra_data or {}))
                    )
                    logger.info(f"📥 [入列] {action}: {rel_path}")
            except Exception as e:
                logger.error(f"DB Insert Error: {e}")
            finally:
                conn.close()

    def get_pending_task(self):
        with self.lock:
            conn = self._get_conn()
            try:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 只有到时间的任务才会被取出
                cursor = conn.execute(
                    f"SELECT * FROM tasks WHERE status IN (?, ?) AND next_retry_at <= ? ORDER BY created_at ASC LIMIT 1",
                    (TaskStatus.PENDING, TaskStatus.RETRY, now_str)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def mark_done(self, task_id):
        with self.lock:
            conn = self._get_conn()
            try:
                with conn:
                    cursor = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                    if cursor.rowcount == 0:
                        logger.warning(f"⚠️ 尝试删除任务 {task_id}，但该任务不存在！")
            except Exception as e:
                logger.error(f"❌ 删除任务失败: {e}")
            finally:
                conn.close()

    def mark_failed(self, task_id):
        with self.lock:
            conn = self._get_conn()
            try:
                with conn:
                    cursor = conn.execute("SELECT retry_count FROM tasks WHERE id=?", (task_id,))
                    row = cursor.fetchone()
                    if not row: return
                    
                    curr_retry = row["retry_count"]
                    # 指数退避：2, 4, 8, 16, 32... 秒
                    wait_seconds = 2 ** curr_retry
                    next_time = datetime.now() + timedelta(seconds=wait_seconds)
                    
                    conn.execute(
                        "UPDATE tasks SET status=?, retry_count=retry_count+1, next_retry_at=? WHERE id=?", 
                        (TaskStatus.RETRY, next_time.strftime("%Y-%m-%d %H:%M:%S"), task_id)
                    )
                    logger.warning(f"❌ 任务 {task_id} 失败，将在 {wait_seconds}s 后重试")
            except Exception as e:
                logger.error(f"❌ 标记失败记录异常: {e}")
            finally:
                conn.close()