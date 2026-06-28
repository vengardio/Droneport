import threading

MAX_QUEUE_SIZE = 255


class MessageQueue:
    """
    Thread-safe кольцевая очередь сообщений.
    Аналог message_queue.c из Drone-gun:
        push()      — добавить (при переполнении дропает старейший)
        pop()       — прочитать и удалить старейший
        peek_last() — прочитать новейший без удаления
        size()      — количество сообщений в очереди
    """

    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._q = []
        self._max = max_size
        self._lock = threading.Lock()

    def push(self, msg):
        with self._lock:
            if len(self._q) >= self._max:
                self._q.pop(0)
            self._q.append(msg)

    def pop(self):
        with self._lock:
            if self._q:
                return self._q.pop(0)
            return None

    def peek_last(self):
        with self._lock:
            if self._q:
                return self._q[-1]
            return None

    def size(self) -> int:
        with self._lock:
            return len(self._q)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._q) == 0


# Три глобальные очереди
server_q = MessageQueue()
drone_q  = MessageQueue()
