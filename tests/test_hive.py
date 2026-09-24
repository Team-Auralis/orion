"""Tiny unit tests for the ORION-HIVE prototype: device envelope contract,
token-weighted FedAvg aggregation, and transport abstractions (pipe & TCP socket)."""

import socket
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import torch

from hive.envelope import (
    ROLE_EVAL,
    ROLE_LIGHTWEIGHT,
    ROLE_PRIMARY,
    declare_device,
)
from hive.aggregation import fedavg, loss_reduction_pct, mse
from hive.transport import TcpSocketTransport


def test_envelope_carries_declared_capability():
    env = declare_device("dev-1", ROLE_PRIMARY, cpu_threads_budget=3, ram_mb_budget=768)
    assert env.device_id == "dev-1"
    assert env.role == ROLE_PRIMARY
    assert env.cpu_threads_budget == 3
    assert env.transport == "multiprocessing-pipe"

    # a device re-probes its own tok/s and re-declares (capability update)
    updated = env.with_tps(1234.5)
    assert updated.tokens_per_sec_estimate == 1234.5
    assert updated.cpu_threads_budget == 3  # the rest of the envelope is preserved

    with pytest.raises(ValueError):
        declare_device("bad", "no-such-role", cpu_threads_budget=1)


def test_fedavg_weights_by_tokens_trained():
    # Two "workers": worker A trained 10 tokens, worker B trained 30 tokens.
    a = {"w": torch.tensor([1.0, 0.0]), "b": torch.tensor([0.5])}
    b = {"w": torch.tensor([0.0, 2.0]), "b": torch.tensor([0.0])}
    agg = fedavg([(a, 10), (b, 30)])
    # weighted average of w: (10*[1,0] + 30*[0,2]) / 40 = [0.25, 1.5]
    assert torch.allclose(agg["w"], torch.tensor([0.25, 1.5]))
    assert torch.allclose(agg["b"], torch.tensor([0.125]))  # (10*0.5+30*0)/40

    # a single update passes through unchanged (resume/full-fleet edge)
    one = fedavg([(a, 10)])
    assert mse(one, a) < 1e-6

    with pytest.raises(ValueError):
        fedavg([])


def test_loss_reduction_pct():
    assert loss_reduction_pct(1.0, 0.5) == 50.0
    assert loss_reduction_pct(1.0, 1.3) == 0.0  # a rising loss is not a reduction
    assert loss_reduction_pct(0.0, 0.1) == 0.0  # no meaningful start


def test_tcp_socket_transport_roundtrip():
    """Verify TcpSocketTransport framing, poll, and byte counting over real loopback sockets."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(1)

    received_msg = []

    def client_thread():
        c_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c_sock.connect(("127.0.0.1", port))
        tx = TcpSocketTransport(c_sock)
        # receive sync
        msg = tx.recv()
        received_msg.append(msg)
        # send update
        tx.send({"type": "update", "tokens": 100, "loss": 2.34})
        tx.close()

    t = threading.Thread(target=client_thread)
    t.start()

    conn, _ = server_sock.accept()
    srv_tx = TcpSocketTransport(conn)
    # send payload
    srv_tx.send({"type": "sync", "data": [1, 2, 3]})
    assert srv_tx.poll(timeout=2.0)
    client_resp = srv_tx.recv()
    assert client_resp["type"] == "update"
    assert client_resp["tokens"] == 100
    assert srv_tx.bytes > 0

    srv_tx.close()
    server_sock.close()
    t.join()
    assert received_msg[0]["type"] == "sync"
