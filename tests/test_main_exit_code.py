import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts import manage_porkbun


@pytest.fixture
def stub_main_dependencies(monkeypatch):
    """Stub out everything main() touches before it reaches the sync-failure
    code path under test, so no real I/O or network calls happen."""
    monkeypatch.setattr(manage_porkbun, "setup_logging", lambda verbose=False: None)
    monkeypatch.setattr(manage_porkbun, "discover_base_dir", lambda: None)
    monkeypatch.setattr(
        manage_porkbun,
        "init_config",
        lambda: {
            "domains": ["example.com"],
            manage_porkbun.PORKBUN_PUBLIC_API_KEY: "pub",
            manage_porkbun.PORKBUN_PRIVATE_API_KEY: "priv",
            "porkbun_rest_endpoint": "https://example.invalid",
        },
    )
    monkeypatch.setattr(
        manage_porkbun, "check_credentials", lambda: {"status": "SUCCESS", "yourIp": "1.2.3.4"}
    )
    monkeypatch.setattr(manage_porkbun, "process_templates", lambda app_config: None)
    monkeypatch.setattr(manage_porkbun, "copy_files", lambda: None)
    # logger is set by setup_logging normally; main() uses the module-level
    # logger directly via calls like logger.info, so make sure it's usable.
    monkeypatch.setattr(manage_porkbun, "logger", manage_porkbun.logging.getLogger("test"))


def test_main_reports_critical_and_exits_1_on_sync_failure(monkeypatch, stub_main_dependencies):
    calls = []
    monkeypatch.setattr(manage_porkbun, "sync_domains", lambda *a, **k: False)
    monkeypatch.setattr(manage_porkbun, "report_service_check", lambda status: calls.append(status))

    with pytest.raises(SystemExit) as exc_info:
        manage_porkbun.main.callback(dry_run=False, verbose=False, domain=None, catch_up=False)

    assert calls == [2]
    assert exc_info.value.code == 1


def test_main_reports_ok_and_does_not_exit_on_sync_success(monkeypatch, stub_main_dependencies):
    calls = []
    monkeypatch.setattr(manage_porkbun, "sync_domains", lambda *a, **k: True)
    monkeypatch.setattr(manage_porkbun, "report_service_check", lambda status: calls.append(status))

    # Should not raise SystemExit
    manage_porkbun.main.callback(dry_run=False, verbose=False, domain=None, catch_up=False)

    assert calls == [0]


def test_main_catch_up_mode_exits_nonzero_on_domain_failure(monkeypatch, stub_main_dependencies):
    """A domain raising during catch-up mode's diff loop must still cause a
    nonzero exit, mirroring normal-sync mode's sync_ok handling -- otherwise
    a catch-up run can silently miss a domain's data and still exit 0."""

    def raising_load_domain(domain_name):
        raise RuntimeError("boom")

    monkeypatch.setattr(manage_porkbun, "load_domain", raising_load_domain)

    with pytest.raises(SystemExit) as exc_info:
        manage_porkbun.main.callback(dry_run=False, verbose=False, domain=None, catch_up=True)

    assert exc_info.value.code == 1


@pytest.mark.parametrize("sync_result", [True, False])
def test_main_dry_run_never_reports_service_check(monkeypatch, stub_main_dependencies, sync_result):
    calls = []
    monkeypatch.setattr(manage_porkbun, "sync_domains", lambda *a, **k: sync_result)
    monkeypatch.setattr(manage_porkbun, "report_service_check", lambda status: calls.append(status))

    # main() still honors sync_ok for its own exit code regardless of
    # dry_run; what we're asserting here is that report_service_check
    # itself is never invoked while dry_run=True.
    if sync_result:
        manage_porkbun.main.callback(dry_run=True, verbose=False, domain=None, catch_up=False)
    else:
        with pytest.raises(SystemExit):
            manage_porkbun.main.callback(dry_run=True, verbose=False, domain=None, catch_up=False)

    assert calls == []
