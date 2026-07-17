FROM python:3.11-slim

# Optional Docker client used only when PYTHON_EXEC_BACKEND=docker and the
# runtime container is given access to a Docker daemon/socket.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
ENV PYTHONPATH=/app/src

# Use domestic mirrors (Aliyun for apt, Tsinghua for pip) so builds on
# China-region servers don't stall on debian.org / pypi.org. Handles both the
# new deb822 (debian.sources, trixie+) and legacy sources.list layouts.
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true; \
    apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY config/api-requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Active API implementation.
COPY src/ ./src/

# Runtime inputs and local state directories.
COPY data/ ./data/
RUN mkdir -p var/chroma_db var/chat_history var/logs var/artifacts var/cache

EXPOSE 8000

CMD ["uvicorn", "ds_course_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
