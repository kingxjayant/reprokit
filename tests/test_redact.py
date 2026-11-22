"""Tests for server-side secret redaction."""

from __future__ import annotations

import pytest

from app.redact import redact, redact_summary, rule_names


def test_github_classic_token_redacted():
    text, hits = redact("using ghp_1234567890abcdefghijklmnop to push")
    assert "ghp_1234567890abcdefghijklmnop" not in text
    assert "[REDACTED:github_token]" in text
    assert redact_summary(hits) == 1


def test_github_fine_grained_token_redacted():
    text, _ = redact("github_pat_11ABCDEFG0123456789_abcdefghijklmnop")
    assert "github_pat_11ABCDEFG" not in text
    assert "[REDACTED:github_token]" in text


def test_private_key_block_redacted_whole():
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1234567890\nabcdef\n"
        "-----END RSA PRIVATE KEY-----"
    )
    text, _ = redact("here is my key:\n" + block)
    assert "MIIEowIBAAKCAQEA" not in text
    assert "[REDACTED:private_key]" in text


def test_aws_access_key_redacted():
    text, _ = redact("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "[REDACTED:aws_access_key]" in text


def test_assigned_secret_password_redacted():
    text, _ = redact('db_password="hunter2hunter2"')
    assert "hunter2hunter2" not in text
    assert "[REDACTED:assigned_secret]" in text


def test_bearer_token_redacted():
    text, _ = redact("Authorization: Bearer abcdef1234567890abcdef")
    assert "abcdef1234567890abcdef" not in text


def test_url_credentials_redacted_but_host_kept():
    text, _ = redact("postgres://admin:s3cretpw@db.example.com:5432/app")
    assert "s3cretpw" not in text
    assert "db.example.com" in text
    assert "[REDACTED:url_credentials]" in text


def test_unix_home_path_username_removed():
    text, _ = redact("/home/jayant/projects/app/main.py")
    assert "jayant" not in text
    assert "/home/[REDACTED:username]/projects/app/main.py" in text


def test_windows_home_path_username_removed():
    text, _ = redact(r"C:\Users\Jayant\AppData\Local\app.log")
    assert "Jayant" not in text
    assert "[REDACTED:username]" in text


def test_email_redacted():
    text, _ = redact("contact jayant.kumar@example.co.in about it")
    assert "jayant.kumar@example.co.in" not in text
    assert "[REDACTED:email]" in text


def test_jwt_redacted():
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    text, _ = redact("token: " + jwt)
    assert "dozjgNryP4J3jVmNHl0w5N" not in text


def test_supabase_service_key_redacted():
    key = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJyb2xlIjoic2VydmljZV9yb2xlIn0."
        "abc123def456ghi789jkl012mno345pqr678"
    )
    text, _ = redact("SUPABASE_SERVICE_ROLE_KEY=" + key)
    assert "abc123def456" not in text


def test_clean_text_is_untouched():
    clean = "Node 22.11.0 on Ubuntu 24.04; running `npm test` throws a TypeError"
    text, hits = redact(clean)
    assert text == clean
    assert hits == []
    assert redact_summary(hits) == 0


def test_version_numbers_are_not_mistaken_for_secrets():
    clean = "react 18.2.0, node 22.11.0, postgres 16.3"
    text, hits = redact(clean)
    assert text == clean
    assert hits == []


def test_multiple_secrets_counted_separately():
    text = "ghp_1234567890abcdefghijklmnop and ghp_zzzzzzzzzzzzzzzzzzzzzzzz"
    out, hits = redact(text)
    assert out.count("[REDACTED:github_token]") == 2
    assert redact_summary(hits) == 2


def test_redaction_is_idempotent():
    once, _ = redact("ghp_1234567890abcdefghijklmnop")
    twice, hits = redact(once)
    assert once == twice
    assert hits == []


def test_all_rules_have_unique_names():
    names = rule_names()
    assert len(names) == len(set(names))


@pytest.mark.parametrize("empty", ["", None])
def test_empty_input_is_safe(empty):
    text, hits = redact(empty)
    assert text == (empty or "")
    assert hits == []
