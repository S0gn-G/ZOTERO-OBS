"""pytest 配置：把 zotnotes_tool 根目录加入 sys.path，使测试可导入源码模块。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
