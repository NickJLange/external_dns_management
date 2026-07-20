import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
import scripts.manage_porkbun as mp
from scripts.manage_porkbun import DomainDiff, write_catchup_to_config


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": str(ttl), "prio": prio}


def setup_fake_etc(tmp_path, domain, is_template=False):
    """Create a fake etc/ structure so write_catchup_to_config has files to append to."""
    files_dir = tmp_path / "etc" / "files"
    templates_dir = tmp_path / "etc" / "templates"
    files_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)

    if is_template:
        tmpl = templates_dir / f"{domain}.j2"
        tmpl.write_text(f"[{domain}]\n# existing template content\n")
    else:
        f = files_dir / domain
        f.write_text(f"[{domain}]\n# existing config\n")

    mp.base_dir = tmp_path
    return tmp_path


def test_porkbun_only_record_appended_as_live_entry(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    diff = DomainDiff(porkbun_only=[rec])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# catchup 2026-07-19" in content
    assert "CNAME" in content
    assert "clerk.example.com" in content
    assert "frontend-api.clerk.services" in content
    assert content.count("#") <= 2  # only the header comment, not commented-out records


def test_value_conflict_appended_as_comments(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    pb = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    diff = DomainDiff(value_conflicts=[(pb, cfg)])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# CONFLICT" in content
    assert "# CONFIG:" in content
    assert "74.101.18.186" in content
    assert "# PORKBUN:" in content
    assert "96.246.42.235" in content
    # Neither version should be a live (uncommented) record
    lines = [line for line in content.splitlines() if "eva.example.com" in line]
    assert all(line.strip().startswith("#") for line in lines)


def test_ttl_conflict_appended_as_comments(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    pb = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    diff = DomainDiff(ttl_conflicts=[(pb, cfg)])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# TTL CONFLICT" in content
    assert "# CONFIG-TTL:" in content
    assert "300" in content
    assert "# PORKBUN-TTL:" in content
    assert "600" in content


def test_template_domain_writes_to_j2_file(tmp_path):
    setup_fake_etc(tmp_path, "nicklange.family", is_template=True)
    rec = make_record("new.nicklange.family", "A", "1.2.3.4")
    diff = DomainDiff(porkbun_only=[rec])

    write_catchup_to_config("nicklange.family", diff, "2026-07-19")

    content = (tmp_path / "etc" / "templates" / "nicklange.family.j2").read_text()
    assert "new.nicklange.family" in content
    assert "# TODO: replace raw IPs with template vars if applicable" in content


def test_nothing_written_when_diff_is_empty(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    original = (tmp_path / "etc" / "files" / "example.com").read_text()

    write_catchup_to_config("example.com", DomainDiff(), "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert content == original
