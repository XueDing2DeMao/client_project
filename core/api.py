import os
import math
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import client_settings as settings

logger = logging.getLogger("API")

class LabClientAPI:
    def __init__(self):
        self.base_url = settings.API_URL # 基础URL 192.168.0.1:5000/windows-sy
        self.headers = {'Authorization': f'Bearer {settings.AUTH_TOKEN}'} # 认证头
        self.machine_id = settings.INSTRUMENT_ALIAS # 仪器别名
        self.chunk_size = settings.UPLOAD_CHUNK_SIZE # 分片大小
        
        # === 网络优化: Session复用 + 自动重试 ===
        self.session = requests.Session() # 创建会话
        self.session.headers.update(self.headers) # 统一认证头
        
        # 重试策略: 遇到 500/502/503/504 错误时，自动重试 3 次，间隔指数增长
        retries = Retry(total=settings.MAX_RETRIES, 
                        backoff_factor=1, 
                        status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries) 
        self.session.mount('http://', adapter) 
        self.session.mount('https://', adapter)

    def _safe_request(self, method, endpoint, **kwargs):
        '''异常安全的请求包装器，吞噬异常并返回 (Success, Response)'''
        try:
            url = f"{self.base_url}{endpoint}"
            # 修复：设置默认超时为 10，如果 kwargs 中已有 timeout (如上传时的60s)，则保持不变
            kwargs.setdefault('timeout', 10)
            
            # 直接传入 kwargs，不再手动指定 timeout
            resp = self.session.request(method, url, **kwargs)
            resp.raise_for_status() 
            return True, resp
        except Exception as e:
            logger.error(f"⚠️ API请求失败 [{endpoint}]: {e}")
            return False, None

    # === 普通接口 ===

    def send_audit(self, extra_data):
        '''发送审计日志'''
        extra_data['machine_id'] = self.machine_id
        success, _ = self._safe_request('POST', '/audit', json=extra_data)
        return success

    def send_operation(self, action, rel_path, extra_data):
        '''发送 MKDIR/DELETE/RENAME 操作'''
        payload = {'action': action, 'path': rel_path, 'machine_id': self.machine_id}
        payload.update(extra_data)
        success, _ = self._safe_request('POST', '/operate', json=payload)
        return success

    def check_integrity(self, rel_path, md5):
        '''校验文件一致性'''
        payload = {"relative_path": rel_path, "md5": md5, "machine_id": self.machine_id}
        success, resp = self._safe_request('POST', '/check_integrity', json=payload)
        return resp.json() if success else None

    # === 大文件核心逻辑: 分片 + 断点续传 ===

    def upload_file_chunked(self, local_path, rel_path, file_md5, mtime, progress_callback=None):
        try:
            file_size = os.path.getsize(local_path)
            total_chunks = math.ceil(file_size / self.chunk_size)

            # 1. [断点续传] 询问服务器已有分片
            uploaded_chunks = self._check_server_chunks(file_md5)
            
            logger.info(f"📤 开始上传: {rel_path} (大小: {file_size/1024/1024:.2f}MB, 分片: {total_chunks}, 已跳过: {len(uploaded_chunks)})")

            with open(local_path, 'rb') as f:
                for i in range(total_chunks):
                    # 如果分片已存在，跳过
                    if i in uploaded_chunks:
                        if progress_callback: progress_callback(i + 1, total_chunks)
                        continue

                    f.seek(i * self.chunk_size)
                    chunk_data = f.read(self.chunk_size)
                    
                    # 上传单个分片
                    if not self._upload_single_chunk(chunk_data, i, total_chunks, file_md5, rel_path):
                        return False, 400

                    if progress_callback: 
                        progress_callback(i + 1, total_chunks)

            # 2. [合并] 通知服务器合并文件
            return self._merge_chunks(rel_path, file_md5, mtime)

        except Exception as e:
            logger.error(f"❌ 上传过程严重错误: {e}")
            return False, 500

    def _check_server_chunks(self, file_md5):
        '''查询断点信息'''
        success, resp = self._safe_request('POST', '/upload/check', json={"md5": file_md5})
        if success and resp.status_code == 200:
            return set(resp.json().get("chunks", []))
        return set()

    def _upload_single_chunk(self, data, chunk_index, total_chunks, file_md5, rel_path):
        '''上传单块数据'''
        files = {'file': data}
        data_payload = {
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'md5': file_md5,
            'relative_path': rel_path,
            'machine_id': self.machine_id
        }
        # 延长超时防止大块传输中断
        success, _ = self._safe_request('POST', '/upload/chunk', files=files, data=data_payload, timeout=60)
        return success

    def _merge_chunks(self, rel_path, file_md5, mtime):
        '''请求合并分片'''
        payload = {
            'relative_path': rel_path,
            'md5': file_md5,
            'mtime': mtime,
            'machine_id': self.machine_id
        }
        success, resp = self._safe_request('POST', '/upload/merge', json=payload, timeout=30)
        if success:
            return True, resp.status_code
        return False, 500
