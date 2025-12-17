import os
import hashlib
import logging

logger = logging.getLogger("Utils")

def is_placeholder(path):
    name = os.path.basename(path).lower()
    # 系统的默认命名模式
    placeholder_prefixes =[
        "新建",          # Win: 新建文本文档, 新建文件夹
        "new ",         # Win/Mac: new folder, new text document
        "未命名",        # Mac: 未命名文件夹
        "untitled",     # Linux/Mac: untitled folder
    ]
    return name.startswith(placeholder_prefixes)

def should_ignore(filename):
    '''文件名黑名单过滤'''
    name = os.path.basename(filename).lower()
    ignore_prefixes = ["~", ".", "._"]
    ignore_suffixes = [".tmp", ".bak", ".swp", ".ds_store", "thumbs.db", "desktop.ini"]
    
    if any(name.startswith(p) for p in ignore_prefixes): return True
    if any(name.endswith(s) for s in ignore_suffixes): return True
    return False

def calc_md5(path):
    '''分块计算 MD5，防止大文件 OOM'''
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1048576), b""): 
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.debug(f"MD5 Calculation failed for {path}: {e}")
        return None

def get_rel_path(path, base_dir):
    '''统一相对路径分隔符为 /'''
    try:
        return os.path.relpath(path, base_dir).replace("\\", "/")
    except ValueError:
        return None
