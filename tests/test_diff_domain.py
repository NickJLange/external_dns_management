import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import DomainDiff, diff_domain, gen_key


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": ttl, "prio": prio}


def keyed(record):
    return {gen_key(record): record}


def test_domaindiff_defaults():
    d = DomainDiff()
    assert d.porkbun_only == []
    assert d.config_only == []
    assert d.value_conflicts == []
    assert d.ttl_conflicts == []
    assert d.in_sync == 0
    assert d.skipped_acme == 0


# --- acme filtering ---

def test_acme_records_are_filtered_from_porkbun():
    acme = make_record("_acme-challenge.example.com", "TXT", "sometoken")
    result = diff_domain("example.com", {}, keyed(acme))
    assert result.porkbun_only == []
    assert result.skipped_acme == 1


def test_acme_records_are_filtered_from_desired():
    acme = make_record("_acme-challenge.example.com", "TXT", "sometoken")
    result = diff_domain("example.com", keyed(acme), {})
    assert result.config_only == []
    assert result.skipped_acme == 1


# --- in sync ---

def test_matching_records_counted_as_in_sync():
    rec = make_record("example.com", "A", "1.2.3.4")
    result = diff_domain("example.com", keyed(rec), keyed(rec))
    assert result.in_sync == 1
    assert result.porkbun_only == []
    assert result.config_only == []


# --- porkbun-only ---

def test_porkbun_only_record_no_name_type_match_in_config():
    pb_rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    result = diff_domain("example.com", {}, keyed(pb_rec))
    assert len(result.porkbun_only) == 1
    assert result.porkbun_only[0]["name"] == "clerk.example.com"


# --- config-only ---

def test_config_only_record_no_name_type_match_in_porkbun():
    cfg_rec = make_record("newyork.example.com", "A", "1.2.3.4")
    result = diff_domain("example.com", keyed(cfg_rec), {})
    assert len(result.config_only) == 1
    assert result.config_only[0]["name"] == "newyork.example.com"


# --- value conflicts ---

def test_value_conflict_same_name_type_different_content():
    pb_rec = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg_rec = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    result = diff_domain("example.com", keyed(cfg_rec), keyed(pb_rec))
    assert len(result.value_conflicts) == 1
    pb_out, cfg_out = result.value_conflicts[0]
    assert pb_out["content"] == "96.246.42.235"
    assert cfg_out["content"] == "74.101.18.186"
    assert result.porkbun_only == []
    assert result.config_only == []


# --- TTL conflicts ---

def test_ttl_conflict_same_name_type_content_different_ttl():
    pb_rec = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg_rec = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    result = diff_domain("example.com", keyed(cfg_rec), keyed(pb_rec))
    assert len(result.ttl_conflicts) == 1
    pb_out, cfg_out = result.ttl_conflicts[0]
    assert pb_out["ttl"] == "600"
    assert cfg_out["ttl"] == "300"
    assert result.value_conflicts == []


# --- multiple record types with same name ---

def test_multiple_records_same_name_different_type_not_confused():
    pb_mx = make_record("example.com", "MX", "fwd1.porkbun.com")
    cfg_txt = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all")
    result = diff_domain("example.com", keyed(cfg_txt), keyed(pb_mx))
    assert len(result.porkbun_only) == 1
    assert len(result.config_only) == 1
    assert result.value_conflicts == []


def test_mx_priority_drift_detected_as_value_conflict():
    """MX records with same content but different priority must not appear in-sync."""
    pb_rec = make_record("example.com", "MX", "fwd1.porkbun.com", ttl="600", prio="10")
    cfg_rec = make_record("example.com", "MX", "fwd1.porkbun.com", ttl="600", prio="20")
    result = diff_domain("example.com", keyed(cfg_rec), keyed(pb_rec))
    assert result.in_sync == 0
    assert len(result.value_conflicts) == 1
