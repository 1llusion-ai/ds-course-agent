import asyncio

import pytest
from fastapi import HTTPException

from ds_course_agent.api.chat_application import _GenerationAdmission


def test_generation_admission_caps_active_and_queued_requests() -> None:
    async def scenario() -> None:
        admission = _GenerationAdmission(active_limit=2, queue_limit=1, queue_timeout=1.0)
        first = await admission.acquire()
        second = await admission.acquire()
        queued = asyncio.create_task(admission.acquire())

        await asyncio.sleep(0)
        with pytest.raises(HTTPException) as exc_info:
            await admission.acquire()
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers == {"Retry-After": "1"}

        first.release()
        third = await queued
        second.release()
        third.release()

    asyncio.run(scenario())


def test_generation_admission_rejects_expired_queue() -> None:
    async def scenario() -> None:
        admission = _GenerationAdmission(active_limit=1, queue_limit=1, queue_timeout=0.01)
        active = await admission.acquire()

        with pytest.raises(HTTPException) as exc_info:
            await admission.acquire()
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers == {"Retry-After": "1"}

        active.release()

    asyncio.run(scenario())
