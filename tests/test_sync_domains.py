import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.manage_porkbun as mp


def test_sync_domains_returns_true_when_all_succeed(monkeypatch):
    calls = []

    def fake_process_domain(domain, dry_run=False):
        calls.append(domain)

    monkeypatch.setattr(mp, "process_domain", fake_process_domain)
    result = mp.sync_domains(["a.com", "b.com"], dry_run=True, verbose=False)
    assert result is True
    assert calls == ["a.com", "b.com"]


def test_sync_domains_returns_false_when_one_domain_errors(monkeypatch):
    def fake_process_domain(domain, dry_run=False):
        if domain == "bad.com":
            raise RuntimeError("boom")

    monkeypatch.setattr(mp, "process_domain", fake_process_domain)
    result = mp.sync_domains(["good.com", "bad.com"], dry_run=True, verbose=False)
    assert result is False


def test_sync_domains_continues_after_one_domain_errors(monkeypatch):
    calls = []

    def fake_process_domain(domain, dry_run=False):
        calls.append(domain)
        if domain == "bad.com":
            raise RuntimeError("boom")

    monkeypatch.setattr(mp, "process_domain", fake_process_domain)
    mp.sync_domains(["bad.com", "good.com"], dry_run=True, verbose=False)
    assert calls == ["bad.com", "good.com"]
