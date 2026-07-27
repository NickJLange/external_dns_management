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


def test_main_exits_1_on_sync_failure(monkeypatch, stub_main_dependencies):
    monkeypatch.setattr(manage_porkbun, "sync_domains", lambda *a, **k: False)

    with pytest.raises(SystemExit) as exc_info:
        manage_porkbun.main.callback(dry_run=False, verbose=False, domain=None, catch_up=False)

    assert exc_info.value.code == 1


def test_main_does_not_exit_on_sync_success(monkeypatch, stub_main_dependencies):
    monkeypatch.setattr(manage_porkbun, "sync_domains", lambda *a, **k: True)

    # Should not raise SystemExit
    manage_porkbun.main.callback(dry_run=False, verbose=False, domain=None, catch_up=False)


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
