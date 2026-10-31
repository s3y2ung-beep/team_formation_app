"""1단계 확인: 로그인과 비밀번호 해시. 실제 DB(.env의 DATABASE_URL)를 씀."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from teamapp import config, db

pytestmark = pytest.mark.skipif(
    not config.get_secret("DATABASE_URL"), reason="DATABASE_URL이 없어 DB 시험을 건너뜀"
)

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def login(student_no: str, password: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_student_no").input(student_no)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    return at


def result_text(at: AppTest) -> str:
    messages = [*at.success, *at.info, *at.error]
    return " / ".join(m.value for m in messages)


def test_login_screen_has_required_keys():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.text_input(key="login_student_no")
    assert at.text_input(key="login_password")
    assert at.button(key="login_submit")


def test_admin_login_succeeds():
    at = login("admin", config.get_secret("ADMIN_PASSWORD"))
    assert not at.exception
    assert at.session_state["user_no"] == "admin"
    assert any("관리자 화면" in t.value for t in at.title)
    assert result_text(at).startswith("승인")


def test_wrong_password_is_blocked():
    at = login("admin", "wrong-password")
    assert "user_no" not in at.session_state
    assert result_text(at).startswith("막힘")


def test_unknown_student_is_blocked():
    at = login("9999999", "1234")
    assert "user_no" not in at.session_state
    assert result_text(at).startswith("막힘")


def test_admin_password_is_stored_as_bcrypt_hash():
    pool = db.make_pool(config.get_secret("DATABASE_URL"))
    try:
        db.apply_schema(pool)
        db.ensure_admin(pool, config.get_secret("ADMIN_PASSWORD"))
        user = db.find_user(pool, "admin")
        assert user["password_hash"].startswith("$2")
        assert user["password_hash"] != config.get_secret("ADMIN_PASSWORD")
    finally:
        pool.close()
