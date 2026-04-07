#!/usr/bin/env python3
"""
启动课程助教问答界面
处理 Windows 终端 UTF-8 编码问题
"""
import sys
import os

# 强制 UTF-8 编码（Windows 兼容）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import subprocess

if __name__ == "__main__":
    print("🚀 启动课程助教问答系统...")
    print(f"📚 课程: {os.getenv('COURSE_NAME', '数据科学导论')}")
    print("-" * 50)

    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", "apps/qa.py"], check=True)
    except KeyboardInterrupt:
        print("\n👋 已退出")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)
