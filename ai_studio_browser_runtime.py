"""Drain owned Playwright sync-loop shutdown tasks before closing the loop."""
import asyncio
from contextlib import contextmanager

@contextmanager
def playwright_runtime():
    try:from playwright.sync_api import sync_playwright
    except ImportError as error:raise RuntimeError('Playwright is missing. Run dependency setup before browser generation.') from error
    manager=sync_playwright();loop=None;futures=[]
    try:
        playwright=manager.start()
        if getattr(manager,'_own_loop',False):
            # The installed sync context cancels tasks then immediately closes
            # its owned loop. Retain ownership here so cancellation can finish.
            loop=manager._loop;manager._own_loop=False
        yield playwright
    finally:
        if loop is None and getattr(manager,'_own_loop',False):
            loop=manager._loop;manager._own_loop=False
        connection=getattr(manager,'_connection',None)
        if connection:
            futures=[callback.future for callback in connection._callbacks.values()]
            try:manager.__exit__(None,None,None)
            finally:
                if loop is not None and not loop.is_closed():
                    tasks=asyncio.all_tasks(loop)
                    for task in tasks:task.cancel()
                    if tasks:loop.run_until_complete(asyncio.gather(*tasks,return_exceptions=True))
                    for future in futures:
                        if future.done() and not future.cancelled():future.exception()
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
