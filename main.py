import time
import threading
import logging
from watchdog.observers import Observer
import client_settings as settings
from core.database import TaskQueueDB
from core.watcher import LabFileHandler
from core.worker import start_sync_worker

# 全局日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(settings.CLIENT_LOG_FILE), encoding='utf-8')
    ]
)

def main():
    # 1. 初始化数据库
    db = TaskQueueDB(settings.DB_PATH)

    # 2. 启动同步工作线程 (后台上传 - 支持分片断点续传)
    worker_thread = threading.Thread(target=start_sync_worker, args=(db,), daemon=True)
    worker_thread.start()

    # 3. 启动文件监听 (Watchdog)
    event_handler = LabFileHandler(db)
    observer = Observer()
    observer.schedule(event_handler, str(settings.WATCH_DIR), recursive=True)
    observer.start()

    print(f"👁️ 监控启动 [机器ID: {settings.INSTRUMENT_ALIAS}]: {settings.WATCH_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()

if __name__ == "__main__":
    main()
