import os
import logging
import client_settings as settings
from core.database import TaskQueueDB
from core.api import LabClientAPI
from core.utils import should_ignore, is_placeholder, calc_md5, get_rel_path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Tool")

def run_scan():
    print(f"🔍 开始全量扫描 [机器ID: {settings.INSTRUMENT_ALIAS}]")
    print(f"📁 目标目录: {settings.WATCH_DIR}")
    
    db = TaskQueueDB(settings.DB_PATH)
    api = LabClientAPI()
    
    for root, dirs, files in os.walk(settings.WATCH_DIR):
        dirs[:] = [d for d in dirs if not should_ignore(d)]
        
        for name in files:
            path = os.path.join(root, name)
            
            if should_ignore(path): continue
            try: 
                if is_placeholder(path) and os.path.getsize(path) == 0: continue
            except: continue
            
            try:
                rel = get_rel_path(path, settings.WATCH_DIR)
                md5 = calc_md5(path)
                mtime = os.path.getmtime(path)
                
                # 校验完整性 (Check Integrity)
                result = api.check_integrity(rel, md5)
                
                # 兼容处理：如果 check_integrity 内部吞掉了异常返回 None，视为需要检查
                status = result.get("status") if result else "UNKNOWN"
                
                if status != "MATCH":
                    print(f"👉 发现差异: {rel} [{status}]")
                    db.add_task("UPLOAD", path, rel, extra_data={"md5": md5, "mtime": mtime})
                    
            except Exception as e:
                print(f"❌ 扫描错误 {name}: {e}")

    print("✅ 扫描完成，差异文件已全部加入任务队列。")

if __name__ == "__main__":
    run_scan()
    input("按回车键退出...")
