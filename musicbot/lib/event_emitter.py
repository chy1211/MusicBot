import asyncio
import collections
import inspect
import traceback
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, DefaultDict, List, Set

if TYPE_CHECKING:
    AsyncFuture = asyncio.Future[Any]
else:
    AsyncFuture = asyncio.Future

EventCallback = Callable[..., Any]
EventList = List[EventCallback]
EventDict = DefaultDict[str, EventList]


class EventEmitter:
    def __init__(self) -> None:
        """
        Manage a collection of events and an event loop to run callbacks
        that are also co-routines.
        """
        self._events: EventDict = collections.defaultdict(list)
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._task_pool: Set[AsyncFuture] = set()

    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """
        Trigger all callbacks registered with `event` to be fired using
        the arguments passed to this function.
        """
        if self.loop.is_closed():
            return

        # Audio/FFmpeg callbacks can arrive from worker threads. Dispatch the
        # entire event (including synchronous listeners) on the owning loop.
        # Preserve direct dispatch when the loop has not started yet.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if self.loop.is_running() and running_loop is not self.loop:
            try:
                self.loop.call_soon_threadsafe(partial(self.emit, event, *args, **kwargs))
            except RuntimeError:
                # The loop can close between is_closed() and scheduling.
                return
            return

        if event not in self._events:
            return

        for cb in list(self._events[event]):
            try:
                result = cb(*args, **kwargs)
                # once() unregisters before an async callback starts running.
                if inspect.isawaitable(result):
                    task = asyncio.ensure_future(result, loop=self.loop)
                    if isinstance(task, asyncio.Task):
                        task.set_name(
                            f"MB_EE_{type(self).__name__}_{getattr(cb, '__name__', type(cb).__name__)}"
                        )
                    self._task_pool.add(task)
                    task.add_done_callback(self._task_pool.discard)

            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()

    def on(self, event: str, callback: EventCallback) -> Any:
        """
        Schedule a `callback` to run each time `event` is emitted.
        """
        self._events[event].append(callback)
        return self

    def off(self, event: str, callback: EventCallback) -> Any:
        """
        Remove a scheduled `callback` from the `event` register.
        """
        self._events[event].remove(callback)

        if not self._events[event]:
            del self._events[event]

        return self

    def once(self, event: str, callback: EventCallback) -> Any:
        """
        Schedule a `callback` function to fire only once, the first time
        an `even` gets fired.
        """

        def callback_off(*args: Any, **kwargs: Any) -> Any:
            self.off(event, callback_off)
            return callback(*args, **kwargs)

        return self.on(event, callback_off)
