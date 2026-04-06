@echo off
chcp 65001 >/dev/null
set PYTHONIOENCODING=utf-8
streamlit run app_qa.py
