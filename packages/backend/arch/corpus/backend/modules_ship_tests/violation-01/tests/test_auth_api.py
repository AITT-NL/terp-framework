def test_login_rejects_a_bad_password() -> None:
    assert login('ada', 'wrong') is None
