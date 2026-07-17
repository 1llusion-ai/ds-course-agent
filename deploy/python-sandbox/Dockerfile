FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Keep the image intentionally small and deterministic.  Add/remove packages
# here based on course needs, then set PYTHON_EXEC_DOCKER_IMAGE to the tag you
# build from this Dockerfile.
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    scipy \
    scikit-learn \
    matplotlib

# The runtime command is supplied by PythonSandbox:
#   python -B /workspace/student_code.py
WORKDIR /workspace
