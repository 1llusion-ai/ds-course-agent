FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY config/api-requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Active API implementation.
COPY src/ ./src/

# Runtime inputs and local state directories.
COPY data/ ./data/
RUN mkdir -p var/chroma_db var/chat_history var/logs var/artifacts var/cache

COPY .env ./

EXPOSE 8000

CMD ["uvicorn", "ds_course_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
