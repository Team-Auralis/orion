"""Transport abstraction: real IPC over multiprocessing pipes or LAN TCP sockets, byte-counted.

`comm_bytes` is measured squarely: every payload is pickled once, the byte
length is counted, and those exact bytes go over the wire/pipe. Both SimPipeTransport
and TcpSocketTransport implement the same send/recv/poll contract and keep their own
byte counters, so metrics are directly comparable across local and LAN runs.
"""

from __future__ import annotations

import pickle
import select
import socket
import struct
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

    def close(self) -> None:
        pass


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

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class TcpSocketTransport(Transport):
    """Real TCP socket transport for LAN / multi-device communication.

    Uses length-prefixed binary framing (4-byte big-endian length + pickled payload).
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sent_bytes = 0
        self.recv_bytes = 0

    def _recvall(self, n: int) -> bytearray:
        buf = bytearray(n)
        view = memoryview(buf)
        pos = 0
        while pos < n:
            nbytes = self.sock.recv_into(view[pos:])
            if nbytes == 0:
                raise EOFError("Socket closed while reading")
            pos += nbytes
        return buf

    def send(self, obj) -> None:
        data = pickle.dumps(obj, protocol=4)
        header = struct.pack(">I", len(data))
        payload = header + data
        self.sock.sendall(payload)
        self.sent_bytes += len(payload)

    def recv(self):
        header = self._recvall(4)
        length = struct.unpack(">I", header)[0]
        data = self._recvall(length)
        self.recv_bytes += 4 + length
        return pickle.loads(data)

    def poll(self, timeout: float) -> bool:
        r, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        return bool(r)

    @property
    def bytes(self) -> int:
        return self.sent_bytes + self.recv_bytes

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
