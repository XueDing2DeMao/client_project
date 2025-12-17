import os
import sys
import json
import socket
import platform
from pathlib import Path

# === 1. 基础路径确认 ===
# 确定程序运行的根目录 (兼容 PyInstaller 打包后的 exe 和直接运行 py 脚本)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.resolve()

# === 2. 加载外部配置文件 (client_config.json) ===
CONFIG_FILE = BASE_DIR / 'client_config.json'
EXTERNAL_CONFIG = {}

if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            EXTERNAL_CONFIG = json.load(f)
    except Exception as e:
        print(f"⚠️ 配置文件解析错误: {e}")

# === 3. 智能数据存储路径 (User Data Dir) ===
# 策略：如果开启 'PORTABLE_MODE' 或系统路径获取失败，回退到本地目录
IS_PORTABLE = EXTERNAL_CONFIG.get('PORTABLE_MODE', False)
APP_NAME = "LabSyncClient"

def get_user_data_dir():
    '''获取跨平台的标准用户数据目录'''
    if IS_PORTABLE:
        return BASE_DIR / "user_data"
    
    system = platform.system()
    try:
        if system == "Windows":
            # C:\Users\User\AppData\Local\LabSyncClient
            base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
            if base: return Path(base) / APP_NAME
        elif system == "Darwin":
            # ~/Library/Application Support/LabSyncClient
            return Path.home() / "Library" / "Application Support" / APP_NAME
        else:
            # ~/.local/share/LabSyncClient
            return Path.home() / ".local" / "share" / APP_NAME
    except:
        pass
    return BASE_DIR / "user_data"

DATA_DIR = get_user_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# === 4. 核心文件路径配置 ===

# 数据库与日志 (存放在数据目录，避免权限问题)
DB_PATH = DATA_DIR / 'client_tasks.db'
LOG_DIR = DATA_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
CLIENT_LOG_FILE = LOG_DIR / 'client_service.log'

# 监控目录 (优先读取配置，默认在当前目录下data)
_default_watch = BASE_DIR / 'data'
watch_cfg = EXTERNAL_CONFIG.get('WATCH_DIR')
WATCH_DIR = Path(watch_cfg) if watch_cfg else _default_watch

# === 5. 服务器连接配置 ===
SERVER_IP = EXTERNAL_CONFIG.get('SERVER_IP', '127.0.0.1')
PORT = EXTERNAL_CONFIG.get('PORT', 5000)
AUTH_TOKEN = EXTERNAL_CONFIG.get('AUTH_TOKEN', 'lab-secret-key-universal-2025')
API_URL = f"http://{SERVER_IP}:{PORT}/api"

# 仪器唯一标识 (Machine ID)
INSTRUMENT_ALIAS = EXTERNAL_CONFIG.get('INSTRUMENT_ALIAS', socket.gethostname())

# === 6. 上传优化配置 ===
# 分片大小：4MB (AWS S3 标准块大小)
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024 
# 网络请求最大重试次数
MAX_RETRIES = 3

# === 7. 初始化检查 ===
try:
    if not WATCH_DIR.exists():
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        print(f"📁 [初始化] 已创建监控目录: {WATCH_DIR}")
    print(f"📂 [系统] 数据存储路径: {DATA_DIR}")
except Exception as e:
    print(f"⚠️ [警告] 目录初始化失败: {e}")
