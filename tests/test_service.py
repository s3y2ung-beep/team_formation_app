"""3단계 확인: 명단 읽기, 실제 DB에서의 지원과 투표, 동시 지원, 학생 화면.

DB 시험은 .env의 DATABASE_URL로 실제 Supabase를 씀. 시험마다 명단을 다시 올려 상태를 지움.
"""

import threading
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from teamapp import config, db, roster, rules, service

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "streamlit_app.py")
needs_db = pytest.mark.skipif(not config.get_secret("DATABASE_URL"), reason="DATABASE_URL이 없음")


def read_sample(title: str) -> list[rules.Student]:
    return roster.parse_roster((ROOT / "samples" / f"{title}.csv").read_bytes())


# ---------- 명단 CSV ----------

def test_roster_reads_bom_and_empty_sub_roles():
    students = read_sample("중간")
    assert len(students) == 12
    s4 = next(s for s in students if s.student_no == "2026204")
    assert s4.sub_roles == ()
    s1 = next(s for s in students if s.student_no == "2026201")
    assert s1.sub_roles == ("발표자", "테스터")


@pytest.mark.parametrize(
    "text, problem",
    [
        ("student_no,name,main_role\n1,가,기획자\n", "첫 줄"),
        ("student_no,name,main_role,sub_roles\n1,가,기획자\n", "열이 3개"),
        ("student_no,name,main_role,sub_roles\n1,가,요리사,\n", "6개 역할에 없음"),
        ("student_no,name,main_role,sub_roles\n1,가,기획자,테스터;발표자;보고서 작성자\n", "0~2개"),
        ("student_no,name,main_role,sub_roles\n1,가,기획자,\n1,나,테스터,\n", "두 번"),
        ("student_no,name,main_role,sub_roles\nadmin,가,기획자,\n", "관리자 학번"),
    ],
)
def test_roster_rejects_bad_files(text, problem):
    with pytest.raises(roster.RosterError, match=problem):
        roster.parse_roster(text.encode("utf-8"))


# ---------- 실제 DB에서 시나리오(마감 전까지) ----------

@pytest.fixture(scope="module")
def pool():
    if not config.get_secret("DATABASE_URL"):
        pytest.skip("DATABASE_URL이 없음")
    p = db.make_pool(config.get_secret("DATABASE_URL"))
    db.apply_schema(p)
    db.ensure_admin(p, config.get_secret("ADMIN_PASSWORD"))
    yield p
    p.close()


def run_steps(pool, steps):
    for step in steps:
        if step[0] == "apply":
            _, no, team, expected = step
            got = service.apply(pool, no, team).message
        else:
            _, voter, applicant, yes, expected = step
            got = service.vote(pool, voter, applicant, yes).message
        assert got.startswith(expected), f"{step} -> {got}"


EASY = [
    ("apply", "2026101", 1, "승인"), ("apply", "2026102", 2, "승인"), ("apply", "2026103", 3, "승인"),
    ("apply", "2026104", 1, "대기"), ("vote", "2026101", "2026104", True, "승인"),
    ("apply", "2026105", 2, "대기"), ("vote", "2026102", "2026105", True, "승인"),
    ("apply", "2026107", 1, "대기"), ("vote", "2026101", "2026107", True, "대기"),
    ("vote", "2026104", "2026107", False, "거절"),
    ("apply", "2026106", 3, "대기"), ("vote", "2026103", "2026106", True, "승인"),
]

MEDIUM = [
    ("apply", "2026201", 1, "승인"),
    ("apply", "2026205", 1, "대기"), ("vote", "2026201", "2026205", True, "승인"),
    ("apply", "2026202", 1, "막힘: " + rules.SAME_MAIN_ROLE),
    ("apply", "2026206", 2, "승인"),
    ("apply", "2026209", 2, "대기"), ("vote", "2026206", "2026209", True, "승인"),
    ("apply", "2026210", 2, "대기"), ("vote", "2026206", "2026210", True, "대기"),
    ("vote", "2026209", "2026210", False, "거절"),
    ("apply", "2026203", 3, "승인"), ("apply", "2026211", 4, "승인"),
    ("apply", "2026212", 4, "대기"), ("apply", "2026212", 3, "막힘: " + rules.HAS_PENDING),
]

HARD = [
    ("apply", "2026301", 1, "승인"),
    ("apply", "2026304", 1, "대기"), ("vote", "2026301", "2026304", True, "승인"),
    ("apply", "2026307", 1, "대기"), ("vote", "2026301", "2026307", True, "대기"),
    ("vote", "2026304", "2026307", True, "승인"),
    ("apply", "2026302", 2, "승인"),
    ("apply", "2026308", 2, "대기"), ("vote", "2026302", "2026308", True, "승인"),
    ("apply", "2026305", 2, "대기"), ("apply", "2026306", 2, "대기"),
    ("vote", "2026302", "2026305", True, "대기"), ("vote", "2026308", "2026305", True, "승인"),
    ("vote", "2026302", "2026306", True, "대기"), ("vote", "2026308", "2026306", True, "대기"),
    ("vote", "2026305", "2026306", True, "거절: 승인 직전 검사에서 " + rules.SAME_MAIN_ROLE),
    ("apply", "2026311", 3, "승인"),
    ("apply", "2026315", 3, "대기"), ("vote", "2026311", "2026315", True, "승인"),
    ("apply", "2026314", 3, "막힘: " + rules.SEAT_SHORTAGE),
    ("apply", "2026310", 4, "승인"),
    ("apply", "2026313", 1, "대기"), ("vote", "2026301", "2026313", True, "대기"),
]


@needs_db
@pytest.mark.parametrize("title, teams, steps", [("쉬움", 3, EASY), ("중간", 4, MEDIUM), ("어려움", 4, HARD)])
def test_practice_scenarios_on_db(pool, title, teams, steps):
    assert service.reset_board(pool, read_sample(title), teams).status == "승인"
    run_steps(pool, steps)


@needs_db
def test_vote_rules_on_db(pool):
    service.reset_board(pool, read_sample("쉬움"), 3)
    run_steps(pool, EASY[:4])  # 학생4가 팀1에 지원해 대기 중
    # 팀원이 아닌 학생은 투표할 수 없음
    assert service.vote(pool, "2026102", "2026104", True).status == "막힘"
    # 한 번 투표하면 바꿀 수 없음(결과가 났으므로 지금 상태인 승인을 보여 줌)
    assert service.vote(pool, "2026101", "2026104", True).status == "승인"
    assert service.vote(pool, "2026101", "2026104", False).status == "승인"


@needs_db
def test_password_is_hashed_and_student_can_log_in(pool):
    service.reset_board(pool, read_sample("쉬움"), 3)
    user = db.find_user(pool, "2026101")
    assert user["password_hash"].startswith("$2") and user["password_hash"] != "1234"
    assert db.verify_login(pool, "2026101", "1234")
    assert db.verify_login(pool, "2026101", "0000") is None


@needs_db
def test_reset_keeps_admin(pool):
    service.reset_board(pool, read_sample("쉬움"), 3)
    service.reset_board(pool, read_sample("중간"), 4)
    assert db.find_user(pool, "admin")["is_admin"]
    board = service.load_board(pool)
    assert len(board.students) == 12 and len(board.teams) == 4
    assert all(not ms for ms in board.teams.values()) and not board.pending


@needs_db
def test_simultaneous_applies_to_last_seat(pool):
    """빈 팀에 두 학생이 같은 순간 지원해도 한 명만 바로 승인됨(나머지는 대기)."""
    service.reset_board(pool, read_sample("쉬움"), 3)
    results = {}
    barrier = threading.Barrier(2)

    def go(no):
        barrier.wait()
        results[no] = service.apply(pool, no, 1).status

    threads = [threading.Thread(target=go, args=(no,)) for no in ("2026101", "2026104")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()) == ["대기", "승인"]
    assert len(service.load_board(pool).teams[1]) == 1


@needs_db
def test_db_unique_constraint_blocks_second_team(pool):
    """앱 검사를 건너뛰고 DB에 직접 넣어도 한 학생은 한 팀에만 들어감."""
    import psycopg

    service.reset_board(pool, read_sample("쉬움"), 3)
    service.apply(pool, "2026101", 1)
    with pool.connection() as conn:
        sid = conn.execute("select id from tf_students where student_no = '2026101'").fetchone()["id"]
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("insert into tf_members (team_id, slot_no, student_id) values (2, 1, %s)", (sid,))


# ---------- 학생 화면(AppTest) ----------

def login(student_no: str, password: str = "1234") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_student_no").input(student_no)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    return at


def result_of(at: AppTest) -> str:
    return " / ".join(m.value for m in [*at.success, *at.info, *at.error])


@needs_db
def test_student_screen_easy_steps(pool):
    service.reset_board(pool, read_sample("쉬움"), 3)
    s1 = login("2026101")
    assert not s1.exception
    for n in (1, 2, 3):
        assert s1.button(key=f"apply_{n}")

    # 1단계: 학생1이 팀1에 지원 -> 승인, 그 뒤로는 지원 단추가 비활성
    s1.button(key="apply_1").click().run()
    assert result_of(s1).startswith("승인")
    assert s1.button(key="apply_2").disabled

    # 2단계: 학생4가 팀1에 지원 -> 대기, 학생1이 찬성 -> 승인
    s4 = login("2026104")
    s4.button(key="apply_1").click().run()
    assert result_of(s4).startswith("대기")
    s1.run()  # 화면 다시 그리기(자동 갱신에 해당)
    s1.button(key="vote_yes_2026104").click().run()
    assert result_of(s1).startswith("승인")

    # 4단계 일부: 학생7이 팀1에 지원, 학생1 찬성 -> 대기, 이미 투표한 학생1은 단추 대신 내 투표 표시
    s7 = login("2026107")
    s7.button(key="apply_1").click().run()
    s1.run()
    s1.button(key="vote_yes_2026107").click().run()
    assert result_of(s1).startswith("대기")
    keys = {b.key for b in s1.button}
    assert "vote_yes_2026107" not in keys and "vote_no_2026107" not in keys
    assert any("내 투표: 찬성" in m.value for m in s1.markdown)

    # 학생4가 거부 -> 거절
    s4.run()
    s4.button(key="vote_no_2026107").click().run()
    assert result_of(s4).startswith("거절")


@needs_db
def test_student_cannot_see_admin_controls(pool):
    service.reset_board(pool, read_sample("쉬움"), 3)
    s1 = login("2026101")
    keys = {b.key for b in s1.button}
    assert not {"admin_start", "admin_close", "admin_assign", "admin_confirm"} & keys
