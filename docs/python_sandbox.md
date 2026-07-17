# Python Execution Sandbox

Explicit "run/execute/look at the output" requests use `PythonSandbox`.  Code
review requests do **not** execute student code.

## Default policy

The default runtime policy is fail-closed:

```env
PYTHON_EXEC_ENABLED=true
PYTHON_EXEC_BACKEND=docker
PYTHON_EXEC_ALLOW_HOST_FALLBACK=false
PYTHON_EXEC_DOCKER_IMAGE=python:3.11-slim
PYTHON_EXEC_TIMEOUT_SECONDS=5
PYTHON_EXEC_MAX_CONCURRENT=2
PYTHON_EXEC_BUSY_TIMEOUT_SECONDS=0
PYTHON_EXEC_MAX_OUTPUT_CHARS=4000
PYTHON_EXEC_MEMORY_MB=256
PYTHON_EXEC_CPUS=0.5
PYTHON_EXEC_TMPFS_MB=64
PYTHON_EXEC_PIDS_LIMIT=64
```

If Docker is unavailable, the agent returns a clear "safe sandbox unavailable"
message and does **not** run code on the host.

## Concurrency limit and busy behavior

`PYTHON_EXEC_MAX_CONCURRENT` bounds how many Python executions may run at the
same time in one backend process.  The default is `2`.

`PYTHON_EXEC_BUSY_TIMEOUT_SECONDS` controls how long a request waits for an
execution slot.  The default `0` is fail-fast: if all slots are occupied, the
agent returns `sandbox_busy=true`, `exit_code=-1`, and tells the user that the
code execution queue is busy.  In this busy path the submitted code is **not**
executed.

## Query trace observability

The sandbox emits best-effort query trace events for execution start, result,
disabled, and busy paths.  Event metadata includes backend, Docker image,
timeout, truncation, `sandbox_disabled`, `sandbox_busy`, and
`unsafe_host_fallback`.  Trace failures are swallowed so observability problems
do not affect code execution or fail-closed responses.

## Docker hardening

The backend starts containers with:

- `--pull=never`
- `--network=none`
- `--read-only`
- non-root UID/GID `65534:65534`
- memory / CPU / pids limits
- `--cap-drop=ALL`
- `--security-opt no-new-privileges`
- read-only `/workspace` containing only the submitted script
- tmpfs `/tmp`

Because `--pull=never` is used, deployment must pre-pull or build the configured
image before serving user requests.

## Recommended course image

For data-science examples, build the provided image:

```bash
docker build -t ds-course-python-sandbox:latest -f deploy/python-sandbox/Dockerfile .
```

Then set:

```env
PYTHON_EXEC_DOCKER_IMAGE=ds-course-python-sandbox:latest
```

The template image includes `numpy`, `pandas`, `scipy`, `scikit-learn`, and
`matplotlib`.  Add other packages only if the course requires them.

## Backend container deployment note

If the API itself runs in Docker and must start sibling sandbox containers, the
backend container needs access to the Docker daemon and the sandbox image must be
available to that daemon.  A typical Docker-outside-of-Docker setup mounts:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Only do this on a trusted host, because Docker socket access is powerful.  Keep
`PYTHON_EXEC_ALLOW_HOST_FALLBACK=false` even in this mode.

The provided `deploy/compose.yaml` disables Python execution by default
(`PYTHON_EXEC_ENABLED=false`) so a fresh compose deployment is not silently
configured to use a Docker daemon it cannot access.  To enable code execution in
compose, set `PYTHON_EXEC_ENABLED=true`, mount `/var/run/docker.sock`, and make
sure `PYTHON_EXEC_DOCKER_IMAGE` exists on that daemon (for example by building
the course sandbox image above).

## Trusted local development

For fast local tests on a trusted machine only, you can explicitly opt into host
execution:

```env
PYTHON_EXEC_BACKEND=local
```

or:

```env
PYTHON_EXEC_BACKEND=docker
PYTHON_EXEC_ALLOW_HOST_FALLBACK=true
```

Do not enable host fallback in production or for untrusted students.

## Optional real Docker integration tests

The unit tests mock Docker command construction.  To exercise real containers:

```bash
docker build -t ds-course-python-sandbox:latest -f deploy/python-sandbox/Dockerfile .
PYTHON_EXEC_DOCKER_IMAGE=ds-course-python-sandbox:latest \
  pytest -q -m docker tests/integration/test_python_sandbox_docker.py
```

The tests skip automatically when Docker is unavailable.
