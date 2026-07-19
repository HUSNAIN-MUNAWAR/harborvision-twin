from __future__ import annotations

from harborvision.security import hash_password, verify_password


def test_password_hash_uses_salt_and_pbkdf2():
    first = hash_password("a secure password")
    second = hash_password("a secure password")
    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password("a secure password", first)
    assert not verify_password("wrong", first)
