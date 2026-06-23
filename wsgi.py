"""
PythonAnywhere WSGI 入口文件

PythonAnywhere Web 配置中 WSGI configuration file 指向此文件即可。
"""
import sys
import os

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from web.app import app as application
