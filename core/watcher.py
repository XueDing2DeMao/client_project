import time
import os
import uuid
import threading
import logging
from watchdog.events import FileSystemEventHandler
from .utils import is_placeholder, should_ignore, calc_md5, get_rel_path
import client_settings as settings

logger = logging.getLogger("Watcher")

class DebounceScanner:
    '''防抖逻辑：文件写入停止 STABILITY_WAIT 秒后才触发上传'''
    def __init__(self, handler, stability_wait=3.0, scan_interval=1.0):
        self.handler = handler
        self.stability_wait = stability_wait
        self.scan_interval = scan_interval
        self.pending = {}
        self.lock = threading.Lock()
        self.running = True

    def touch(self, path):
        with self.lock:
            self.pending[path] = time.time()

    def run(self):
        while self.running:
            time.sleep(self.scan_interval)
            now = time.time()
            stable = []
            with self.lock:
                for path, t in list(self.pending.items()):
                    if now - t > self.stability_wait:
                        stable.append(path)
                        del self.pending[path]
            for path in stable:
                self.handler.process_stable_file(path)

class LabFileHandler(FileSystemEventHandler):
    def __init__(self, db):
        self.db = db
        self.machine_id = settings.INSTRUMENT_ALIAS
        self.debouncer = DebounceScanner(self)
        threading.Thread(target=self.debouncer.run, daemon=True).start()

    def _audit(self, event_type, path, old_path=None):
        rel = get_rel_path(path, settings.WATCH_DIR)
        old_rel = get_rel_path(old_path, settings.WATCH_DIR) if old_path else None
        if not rel: return
        self.db.add_task("AUDIT", "", "", extra_data={
            "id": str(uuid.uuid4()), 
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "machine_id": self.machine_id, 
            "event": event_type, 
            "path": rel, "old_path": old_rel
        })

    def process_stable_file(self, path):
        if not os.path.exists(path) or os.path.isdir(path): return
        rel = get_rel_path(path, settings.WATCH_DIR)
        if not rel: return
        
        # 尝试独占打开，确保文件未被占用
        try:
            with open(path, 'ab'): pass
        except PermissionError:
            self.debouncer.touch(path) # 继续等待
            return
        except: return

        md5 = calc_md5(path)
        mtime = os.path.getmtime(path)
        if md5:
            self.db.add_task("UPLOAD", path, rel, extra_data={"md5": md5, "mtime": mtime})

    def on_created(self, event):
        if should_ignore(event.src_path): return
        if event.is_directory:
            rel = get_rel_path(event.src_path, settings.WATCH_DIR)
            if rel: self.db.add_task("MKDIR", "", rel)
        else:
            # 忽略0KB占位符
            if is_placeholder(event.src_path):
                try: 
                    if os.path.getsize(event.src_path) == 0: return
                except: pass
            self.debouncer.touch(event.src_path)
            self._audit("CREATED", event.src_path)

    def on_modified(self, event):
        if should_ignore(event.src_path): return
        if not event.is_directory:
            self.debouncer.touch(event.src_path)

    def on_moved(self, event):
        src_ign, dst_ign = should_ignore(event.src_path), should_ignore(event.dest_path)
        if src_ign and dst_ign: return
        if src_ign and not dst_ign:
            # 视为新建
            if not event.is_directory: self.debouncer.touch(event.dest_path)
            return

        old_rel = get_rel_path(event.src_path, settings.WATCH_DIR)
        new_rel = get_rel_path(event.dest_path, settings.WATCH_DIR)
        if old_rel and new_rel:
            self.db.add_task("RENAME", "", old_rel, extra_data={"new_path": new_rel})
            self._audit("MOVED", event.dest_path, old_path=event.src_path)

    def on_deleted(self, event):
        if should_ignore(event.src_path): return
        rel = get_rel_path(event.src_path, settings.WATCH_DIR)
        if rel:
            self.db.add_task("DELETE", "", rel, extra_data={"is_dir": event.is_directory})
            self._audit("DELETED", event.src_path)
