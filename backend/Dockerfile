FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Active API implementation plus transitional backend assets.
COPY apps/ ./apps/
COPY backend/ ./backend/

# Core runtime modules.
COPY core/ ./core/
COPY skills/ ./skills/
COPY utils/ ./utils/
COPY kb_builder/ ./kb_builder/
COPY eval/ ./eval/

# Local data and persisted runtime state.
COPY data/ ./data/
COPY chroma_db/ ./chroma_db/
COPY chat_history/ ./chat_history/

COPY .env ./

EXPOSE 8000

CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
