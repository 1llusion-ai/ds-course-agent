@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo 启动课程助教问答系统...
streamlit run app_qa.py
