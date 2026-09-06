"""A prompt stays owned by its worker through pi's automatic continuations."""
import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from pilot.pi_rpc import PiRPC


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_prompt_waits_for_settled_after_retry(success):
    rpc = PiRPC("pi", [], "/tmp", AsyncMock())
    rpc.send = AsyncMock(return_value={"success": True})
    rpc._event_queue = asyncio.Queue()
    dispatcher = asyncio.create_task(rpc._dispatch_events())
    prompt = asyncio.create_task(rpc.prompt_and_wait("hello"))
    try:
        await asyncio.sleep(0)
        for event in [
            {"type": "agent_start"},
            {"type": "agent_end", "willRetry": True},
            {"type": "auto_retry_start"},
            {"type": "agent_start"},
            {"type": "agent_end", "willRetry": False},
            {"type": "auto_retry_end", "success": success},
        ]:
            rpc._handle_stdout_message(event)
            await rpc._event_queue.join()
            assert not rpc._agent_done.is_set()
            assert not prompt.done()

        rpc._handle_stdout_message({"type": "agent_settled"})
        await asyncio.wait_for(prompt, timeout=1)
        assert rpc._agent_finished
        assert rpc.on_event.call_args.args[0]["type"] == "agent_settled"
    finally:
        prompt.cancel()
        dispatcher.cancel()
        with suppress(asyncio.CancelledError):
            await prompt
        with suppress(asyncio.CancelledError):
            await dispatcher


@pytest.mark.asyncio
async def test_agent_end_without_retry_still_waits_for_compaction():
    rpc = PiRPC("pi", [], "/tmp", AsyncMock())
    rpc._reset_agent_tracking()
    rpc._event_queue = asyncio.Queue()
    dispatcher = asyncio.create_task(rpc._dispatch_events())
    try:
        for event in [
            {"type": "agent_end", "willRetry": False},
            {"type": "compaction_start"},
            {"type": "compaction_end", "willRetry": True},
            {"type": "agent_start"},
            {"type": "agent_end", "willRetry": False},
        ]:
            rpc._handle_stdout_message(event)
            await rpc._event_queue.join()
            assert not rpc._agent_done.is_set()
        rpc._handle_stdout_message({"type": "agent_settled"})
        await rpc._event_queue.join()
        assert rpc._agent_done.is_set()
    finally:
        dispatcher.cancel()
        with suppress(asyncio.CancelledError):
            await dispatcher
