import socket
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import report_service_check


class FakeSocket:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sendto(self, data, addr):
        FakeSocket.sent.append((data, addr))


def test_report_service_check_ok_sends_status_zero(monkeypatch):
    FakeSocket.sent = []
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    report_service_check(0)
    assert len(FakeSocket.sent) == 1
    data, addr = FakeSocket.sent[0]
    assert data == b"_sc|dns.sync.status|0|h:BatchNode"
    assert addr == ("172.17.0.1", 8125)


def test_report_service_check_critical_sends_status_two(monkeypatch):
    FakeSocket.sent = []
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    report_service_check(2)
    data, _ = FakeSocket.sent[0]
    assert data == b"_sc|dns.sync.status|2|h:BatchNode"


def test_report_service_check_respects_env_overrides(monkeypatch):
    FakeSocket.sent = []
    monkeypatch.setenv("DD_AGENT_HOST", "10.88.0.1")
    monkeypatch.setenv("DD_AGENT_PORT", "9125")
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    report_service_check(0)
    _, addr = FakeSocket.sent[0]
    assert addr == ("10.88.0.1", 9125)


def test_report_service_check_never_raises_on_oserror(monkeypatch):
    class RaisingSocket(FakeSocket):
        def sendto(self, data, addr):
            raise OSError("network unreachable")

    monkeypatch.setattr(socket, "socket", lambda *a, **k: RaisingSocket())
    report_service_check(0)  # must not raise


def test_report_service_check_respects_dd_hostname_override(monkeypatch):
    FakeSocket.sent = []
    monkeypatch.setenv("DD_HOSTNAME", "lunarBeacon")
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    report_service_check(0)
    data, _ = FakeSocket.sent[0]
    assert data == b"_sc|dns.sync.status|0|h:lunarBeacon"


def test_report_service_check_never_raises_on_invalid_port(monkeypatch):
    FakeSocket.sent = []
    monkeypatch.setenv("DD_AGENT_PORT", "not-a-port")
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    report_service_check(0)  # must not raise -- the sync must continue
    assert FakeSocket.sent == []
