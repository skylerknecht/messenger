import asyncio


class TaskSupervisor:

    def __init__(self, update_cli):
        self._tasks = set()
        self._update_cli = update_cli

    def spawn(self, coro, *, label):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._on_done(t, label))
        return task

    def _on_done(self, task, label):
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None or isinstance(exc, asyncio.CancelledError):
            return
        self._update_cli.display(
            f'Background task failed: {label}', 'error', reprompt=False)
        self._update_cli.log_unexpected_error(exc)

    async def cancel_all(self):
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
