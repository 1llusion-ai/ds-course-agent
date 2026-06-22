from __future__ import annotations

import shutil
import tempfile
import inspect
import os
from pathlib import Path
from uuid import uuid4

import pytest


os.environ.setdefault("KNOWLEDGE_MAPPER_DISABLE_ONLINE_EMBEDDINGS", "1")


def _patch_httpx_client_app_kwarg_for_starlette_testclient() -> None:
    """Make Starlette 0.35 TestClient work with httpx >= 0.28 in tests.

    Starlette's TestClient in the FastAPI version used by this project still
    passes an ``app=`` keyword to ``httpx.Client``. httpx 0.28 removed that
    keyword, which breaks backend test collection before fixtures can run.
    The TestClient already passes the ASGI transport separately, so dropping
    this obsolete keyword preserves the intended test behavior.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - tests requiring TestClient need httpx
        return

    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return

    original_init = httpx.Client.__init__
    if getattr(original_init, "_ds_course_agent_app_kwarg_patch", False):
        return

    def patched_init(self, *args, **kwargs):
        kwargs.pop("app", None)
        return original_init(self, *args, **kwargs)

    patched_init._ds_course_agent_app_kwarg_patch = True
    httpx.Client.__init__ = patched_init


_patch_httpx_client_app_kwarg_for_starlette_testclient()


class SameThreadASGITestClient:
    """Small sync ASGI test client that avoids Starlette's thread portal.

    The Starlette version pinned by this project builds ``TestClient`` on an
    AnyIO blocking portal running in another thread. In this sandbox/CI setup,
    the portal's cross-thread event-loop wakeup can be blocked, which makes
    even simple requests hang. Backend tests only need synchronous HTTP-style
    calls, so this wrapper drives ``httpx.ASGITransport`` in the current thread
    and returns normal ``httpx.Response`` objects.
    """

    __test__ = False

    def __init__(
        self,
        app,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        headers: dict | None = None,
        cookies=None,
        follow_redirects: bool = True,
        **_ignored,
    ) -> None:
        import httpx

        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.root_path = root_path
        self.follow_redirects = follow_redirects
        self.headers = httpx.Headers(headers or {})
        self.headers.setdefault("user-agent", "testclient")
        self.cookies = httpx.Cookies(cookies)

    def request(
        self,
        method: str,
        url,
        *,
        content=None,
        data=None,
        files=None,
        json=None,
        params=None,
        headers=None,
        cookies=None,
        auth=None,
        follow_redirects: bool | None = None,
        allow_redirects: bool | None = None,
        timeout=None,
        extensions=None,
        **kwargs,
    ):
        import anyio
        import httpx

        if allow_redirects is not None:
            redirect = allow_redirects
        elif follow_redirects is not None:
            redirect = follow_redirects
        else:
            redirect = self.follow_redirects

        request_headers = self.headers.copy()
        if headers:
            request_headers.update(headers)

        request_cookies = httpx.Cookies(self.cookies)
        if cookies:
            request_cookies.update(cookies)

        async def _send():
            transport = httpx.ASGITransport(
                app=self.app,
                raise_app_exceptions=self.raise_server_exceptions,
                root_path=self.root_path,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                headers=request_headers,
                cookies=request_cookies,
                follow_redirects=redirect,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    content=content,
                    data=data,
                    files=files,
                    json=json,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    auth=auth,
                    follow_redirects=redirect,
                    timeout=timeout,
                    extensions=extensions,
                    **kwargs,
                )
                await response.aread()
                self.cookies.update(client.cookies)
                return response

        return anyio.run(_send, backend="asyncio")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return None


def _patch_starlette_testclient_thread_portal() -> None:
    """Use the same-thread test client for this repository's tests."""
    try:
        import fastapi.testclient as fastapi_testclient
        import starlette.testclient as starlette_testclient
    except ImportError:  # pragma: no cover
        return

    fastapi_testclient.TestClient = SameThreadASGITestClient
    starlette_testclient.TestClient = SameThreadASGITestClient


_patch_starlette_testclient_thread_portal()


_TEST_TMP_ROOT = Path(__file__).resolve().parent / "artifacts" / "test_tmp"


def _make_workspace_temp_dir(prefix: str = "tmp", suffix: str = "", base_dir: str | Path | None = None) -> Path:
    base_path = Path(base_dir) if base_dir else (_TEST_TMP_ROOT / "stdlib")
    base_path.mkdir(parents=True, exist_ok=True)

    while True:
        candidate = base_path / f"{prefix}{uuid4().hex}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue


def _workspace_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    temp_dir = _make_workspace_temp_dir(
        prefix=prefix or "tmp",
        suffix=suffix or "",
        base_dir=dir,
    )
    return str(temp_dir)


class WorkspaceTemporaryDirectory:
    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        ignore_cleanup_errors: bool = False,
    ) -> None:
        self.name = _workspace_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors
        self._closed = False

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)
        except Exception:
            if not self._ignore_cleanup_errors:
                raise

    def __del__(self) -> None:  # pragma: no cover - GC timing is non-deterministic
        try:
            self.cleanup()
        except Exception:
            pass


@pytest.fixture(scope="session", autouse=True)
def _patch_tempfile_to_workspace_local():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tempfile, "mkdtemp", _workspace_mkdtemp)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", WorkspaceTemporaryDirectory)
    yield
    monkeypatch.undo()


@pytest.fixture
def tmp_path():
    """Provide a workspace-local temporary directory on Windows.

    Pytest's built-in tmp_path fixture uses an internal basetemp lifecycle that
    has been unreliable in this repository's Windows workspace. We keep the
    same fixture shape but back it with a plain temporary directory under the
    gitignored artifacts tree.
    """

    _TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = _make_workspace_temp_dir(prefix="pytest_", base_dir=_TEST_TMP_ROOT)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
