import time
import json
import logging
import os
from .api import LabClientAPI

logger = logging.getLogger("Worker")

def progress_reporter(current, total):
    '''上传进度回调函数'''
    percent = (current / total) * 100
    # 减少日志刷屏：仅在开始、完成或每20%时打印
    if total < 5 or current == total or current % (total // 5) == 0:
        logger.info(f"    ⏳ 进度: {percent:.0f}% ({current}/{total})")

def start_sync_worker(db):
    '''后台同步线程主循环'''
    api = LabClientAPI() # 初始化一次 Session
    logger.info("🚀 后台同步线程已启动 (优化版: 分片+断点续传)...")
    
    while True:
        task = db.get_pending_task()
        if not task:
            time.sleep(1)
            continue
        
        tid, action, local, rel, extra_str, _, _, _ = task
        extra = json.loads(extra_str)
        success = False
        
        try:
            if action == "UPLOAD":
                if not os.path.exists(local):
                    db.mark_done(tid)
                    continue
                
                # 调用分片上传接口
                is_ok, status_code = api.upload_file_chunked(
                    local_path=local, 
                    rel_path=rel, 
                    file_md5=extra.get('md5'), 
                    mtime=extra.get('mtime'),
                    progress_callback=progress_reporter
                )
                
                if is_ok:
                    success = True
                elif status_code == 409:
                    logger.error(f"❌ 校验冲突: {rel} (服务器已存在且不一致)")
                    # 冲突暂不重试，避免死循环，需人工确认
                else:
                    logger.error(f"❌ 上传失败 code={status_code}: {rel}")
            
            elif action == "AUDIT":
                success = api.send_audit(extra)
            
            elif action in ["MKDIR", "DELETE", "RENAME"]:
                success = api.send_operation(action, rel, extra)
                
        except Exception as e:
            logger.error(f"Sync Logic Error [{action}]: {e}")

        if success:
            db.mark_done(tid)
            logger.info(f"✅ 完成: {action} {rel}")
        else:
            db.mark_failed(tid)
            # 失败退避：失败后等待 3 秒，防止快速频繁请求冲击服务器
            time.sleep(3)
