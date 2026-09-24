"""Transport abstraction: real IPC over multiprocessing pipes, byte-counted.

`comm_bytes` is measured squarely: every payload is pickled once, the byte
length is counted, and those exact bytes go over the pipe. A later LAN/phone
transport (TCP/QUIC/etc.) implements the same send/recv/poll contract and
keeps its own byte counters, so the metrics stay comparable.
"""

from __future__ import annotations

import pickle
from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, obj) -> None: ...

    @abstractmethod
    def recv(self): ...

    @abstractmethod
    def poll(self, timeout: float) -> bool: ...

    @property
    @abstractmethod
    def bytes(self) -> int: ...


class SimPipeTransport(Transport):
    """Localhost sim transport over a real multiprocessing pipe."""

    def __init__(self, conn):
        self._conn = conn
        self.sent_bytes = 0
        self.recv_bytes = 0

    def send(self, obj) -> None:
        data = pickle.dumps(obj, protocol=4)
        self.sent_bytes += len(data)
        self._conn.send_bytes(data)

    def recv(self):
        data = self._conn.recv_bytes()
        self.recv_bytes += len(data)
        return pickle.loads(data)

    def poll(self, timeout: float) -> bool:
        return self._conn.poll(timeout)

    @property
    def bytes(self) -> int:
        return self.sent_bytes + self.recv_bytes
