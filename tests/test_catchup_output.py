import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import DomainDiff, print_catchup_report


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": str(ttl), "prio": prio}


def run_report(domain, diff, capsys):
    print_catchup_report(domain, diff)
    return capsys.readouterr().out


def test_domain_header_printed(capsys):
    out = run_report("example.com", DomainDiff(), capsys)
    assert "=== example.com ===" in out


def test_in_sync_count_printed(capsys):
    diff = DomainDiff(in_sync=42)
    out = run_report("example.com", diff, capsys)
    assert "42 records in sync" in out


def test_porkbun_only_section_shown(capsys):
    rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    diff = DomainDiff(porkbun_only=[rec])
    out = run_report("example.com", diff, capsys)
    assert "PORKBUN-ONLY" in out
    assert "[>]" in out
    assert "clerk.example.com" in out
    assert "frontend-api.clerk.services" in out


def test_config_only_section_shown(capsys):
    rec = make_record("newyork.example.com", "A", "1.2.3.4")
    diff = DomainDiff(config_only=[rec])
    out = run_report("example.com", diff, capsys)
    assert "CONFIG-ONLY" in out
    assert "[+]" in out
    assert "newyork.example.com" in out


def test_value_conflict_shown(capsys):
    pb = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    diff = DomainDiff(value_conflicts=[(pb, cfg)])
    out = run_report("example.com", diff, capsys)
    assert "VALUE CONFLICT" in out
    assert "[~]" in out
    assert "96.246.42.235" in out
    assert "74.101.18.186" in out


def test_ttl_conflict_shown(capsys):
    pb = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    diff = DomainDiff(ttl_conflicts=[(pb, cfg)])
    out = run_report("example.com", diff, capsys)
    assert "TTL CONFLICT" in out
    assert "[t]" in out
    assert "porkbun-ttl=600" in out
    assert "config-ttl=300" in out


def test_skipped_acme_count_shown(capsys):
    diff = DomainDiff(skipped_acme=4)
    out = run_report("example.com", diff, capsys)
    assert "4 _acme-challenge" in out


def test_none_section_shown_when_empty(capsys):
    diff = DomainDiff(in_sync=5)
    out = run_report("example.com", diff, capsys)
    assert "(none)" in out
