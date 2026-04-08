FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装Python依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端应用
COPY backend/app/ ./app/
COPY backend/tests/ ./tests/

# 复制核心模块
COPY core/ ./core/
COPY skills/ ./skills/
COPY utils/ ./utils/
COPY kb_builder/ ./kb_builder/
COPY eval/ ./eval/

# 复制数据和向量数据库
COPY data/ ./data/
COPY chroma_db/ ./chroma_db/
COPY chat_history/ ./chat_history/

# 复制环境变量
COPY .env .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
