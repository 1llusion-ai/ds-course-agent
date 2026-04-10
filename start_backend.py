#!/usr/bin/env python
"""启动后端服务（带正确的SSL配置）"""
import os
import sys

# 设置正确的SSL证书路径
os.environ['SSL_CERT_FILE'] = r'D:\Anaconda\envs\RAG\Library\ssl\cacert.pem'
os.environ['REQUESTS_CA_BUNDLE'] = r'D:\Anaconda\envs\RAG\Library\ssl\cacert.pem'

# 启动uvicorn
os.chdir(r'F:\Projects\RAG_System\backend')
sys.path.insert(0, r'F:\Projects\RAG_System\backend')

import uvicorn
if __name__ == '__main__':
    uvicorn.run('app.main:app', host='127.0.0.1', port=8083, reload=True)
