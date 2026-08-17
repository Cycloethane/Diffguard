# -*- coding: utf-8 -*-
"""pytest 配置：把项目根目录加入 sys.path，便于从 tests/ 直接导入项目模块。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
