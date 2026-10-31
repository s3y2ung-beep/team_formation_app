"""4단계 확인: 직접 배정(solver), AI 응답 읽기, 실패 처리와 120초 제한, 관리자 화면의 마감부터 확정까지."""

import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from teamapp import ai, config, db, roster, rules, service, solver
from teamapp.rules import Assignment, Student

from .memory_board import MemoryBoard
from .test_service import EASY, HARD, MEDIUM, read_sample, run_steps

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "streamlit_app.py")
PL, WP, FD, TT, RW, PT = rules.ROLES


def S(no, main, *subs):
    return Student(no, f"학생{no}", main, subs)


def board_after_close(title, teams, steps) -> MemoryBoard:
    b = MemoryBoard(title, teams)
    for step in steps:
        if step[0] == "apply":
            b.apply(step[1], step[2])
        else:
            b.vote(step[1], step[2], step[3])
    b.close()
    return b


# ---------- 직접 배정(solver) ----------

@pytest.mark.parametrize("title, teams, steps", [("쉬움", 3, EASY), ("중간", 4, MEDIUM), ("어려움", 4, HARD)])
def test_solver_finds_valid_assignment_for_practice_scenarios(title, teams, steps):
    b = board_after_close(title, teams, steps)
    proposal = solver.find_assignment(b.teams, b.unassigned())
    assert proposal is not None
    assert rules.validate_assignment(Assignment(b.teams, b.unassigned(), proposal)) == []


def test_solver_uses_sub_roles():
    # 웹 프로그래머는 보조 역할로만 맡을 수 있는 학생뿐인 경우
    teams = {1: [S("1", PL)], 2: [S("2", PL)]}
    unassigned = [S("3", FD, WP), S("4", TT, WP)]
    proposal = solver.find_assignment(teams, unassigned)
    assert sorted(t for _, t in proposal) == [1, 2]


def test_solver_all_students_unassigned_is_fast():
    students = list(read_sample("어려움"))
    start = time.monotonic()
    proposal = solver.find_assignment({n: [] for n in range(1, 5)}, students)
    assert proposal is not None and time.monotonic() - start < 2


def test_impossible_assignment_is_explained_quickly():
    # 웹 프로그래머를 맡을 수 있는 학생이 한 명도 없는 16명
    students = [s for s in read_sample("어려움") if not s.can(WP)]
    start = time.monotonic()
    assert solver.find_assignment({n: [] for n in range(1, 5)}, students) is None
    assert time.monotonic() - start < 2
    reasons = solver.explain_impossible({n: [] for n in range(1, 5)}, students)
    assert any("웹 프로그래머" in r for r in reasons)


def test_explain_names_the_team_without_web_programmer():
    teams = {1: [S("1", PL), S("2", WP)], 2: []}
    unassigned = [S("3", PL), S("4", FD)]
    assert solver.find_assignment(teams, unassigned) is None
    reasons = solver.explain_impossible(teams, unassigned)
    assert any("팀2에 웹 프로그래머를 맡을 학생이 없음" in r for r in reasons)


# ---------- AI 응답 읽기 ----------

def test_parse_proposal_with_code_fence_and_team_name():
    text = '설명입니다\n```json\n{"assignments": [{"student_no": "1", "team": "팀2"}, {"student_no": 2, "team": 1}]}\n```'
    assert ai.parse_proposal(text) == [("1", 2), ("2", 1)]


@pytest.mark.parametrize("text", ["", "   ", "배정할 수 없습니다", '{"result": []}', "{not json}"])
def test_parse_proposal_failures(text):
    with pytest.raises(ai.ModelFailure):
        ai.parse_proposal(text)


def test_prompt_contains_rules_and_students():
    prompt = ai.build_prompt({1: [S("1", PL)]}, [S("2", WP)])
    assert "기획자" in prompt and "웹 프로그래머" in prompt and '"student_no": "2"' in prompt


# ---------- 1차, 2차, 3차 모델과 직접 배정 ----------

TEAMS = {1: [S("1", PL)], 2: [S("2", PL)]}
UNASSIGNED = [S("3", WP), S("4", FD, WP)]
GOOD = '{"assignments": [{"student_no": "3", "team": 1}, {"student_no": "4", "team": 2}]}'
BAD_RULES = '{"assignments": [{"student_no": "3", "team": 1}, {"student_no": "4", "team": 1}]}'


def fake_caller(answers):
    """모델 이름 차례대로 답(문자열), 예외, 또는 (잠깐 쉬기, 답)을 돌려주는 가짜 호출."""
    calls = iter(answers)

    def call(key, model, prompt):
        answer = next(calls)
        if isinstance(answer, tuple):
            time.sleep(answer[0])
            answer = answer[1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return call


def test_second_model_used_when_first_breaks_rules():
    result = ai.run_assignment(TEAMS, UNASSIGNED, "key", caller=fake_caller([BAD_RULES, GOOD, GOOD]))
    assert result.source.startswith("2차 모델")
    assert result.attempts[0].outcome.startswith("검사 불통과")


def test_empty_answer_and_429_move_to_next_model():
    answers = [ai.ModelFailure("빈 응답"), ai.ModelFailure("HTTP 429 사용량 제한"), GOOD]
    result = ai.run_assignment(TEAMS, UNASSIGNED, "key", caller=fake_caller(answers))
    assert result.source.startswith("3차 모델")
    assert [a.outcome for a in result.attempts[:2]] == ["빈 응답", "HTTP 429 사용량 제한"]


def test_app_assigns_by_itself_after_three_failures():
    answers = [ai.ModelFailure("빈 응답"), "모르겠습니다", BAD_RULES]
    result = ai.run_assignment(TEAMS, UNASSIGNED, "key", caller=fake_caller(answers))
    assert result.source.startswith("앱이 직접 배정")
    assert rules.validate_assignment(Assignment(TEAMS, UNASSIGNED, result.proposal)) == []


def test_slow_model_is_cut_at_total_timeout():
    """응답이 늦으면 전체 대기 시간(여기서는 1초로 줄임)에서 끊고 다음 모델로 넘어감."""
    progress = []
    start = time.monotonic()
    result = ai.run_assignment(
        TEAMS, UNASSIGNED, "key", timeout=1,
        caller=fake_caller([(3, GOOD), (3, GOOD), GOOD]),
        on_progress=lambda order, model, elapsed: progress.append(order),
    )
    assert time.monotonic() - start < 3.5
    assert [a.outcome for a in result.attempts[:2]] == ["시간 초과(1초)", "시간 초과(1초)"]
    assert result.source.startswith("3차 모델")
    assert {1, 2, 3} <= set(progress)  # 몇 차 모델을 기다리는지 안내함


def test_missing_key_fails_without_network():
    with pytest.raises(ai.ModelFailure, match="OPENROUTER_API_KEY"):
        ai.call_openrouter("", ai.MODELS[0], "x")


def test_no_free_router_used():
    assert all(m.endswith(":free") and m != "openrouter/free" for m in ai.MODELS)
    assert len(ai.MODELS) == 3


# ---------- 실제 DB와 관리자 화면 ----------

needs_db = pytest.mark.skipif(not config.get_secret("DATABASE_URL"), reason="DATABASE_URL이 없음")


@pytest.fixture(scope="module")
def pool():
    if not config.get_secret("DATABASE_URL"):
        pytest.skip("DATABASE_URL이 없음")
    p = db.make_pool(config.get_secret("DATABASE_URL"))
    db.apply_schema(p)
    db.ensure_admin(p, config.get_secret("ADMIN_PASSWORD"))
    yield p
    p.close()


def admin_session() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.text_input(key="login_student_no").input("admin")
    at.text_input(key="login_password").input(config.get_secret("ADMIN_PASSWORD"))
    at.button(key="login_submit").click().run()
    return at


def result_of(at: AppTest) -> str:
    return " / ".join(m.value for m in [*at.success, *at.info, *at.error])


def keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


@needs_db
def test_close_rejects_pending_and_removes_lonely_members(pool):
    service.reset_board(pool, read_sample("중간"), 4)
    run_steps(pool, MEDIUM)
    assert service.close_recruitment(pool).status == "승인"
    board = service.load_board(pool)
    assert not board.pending
    left = {s.student_no for s in board.unassigned()}
    assert {"2026203", "2026211", "2026212"} <= left and len(left) == 8
    assert service.close_recruitment(pool).status == "막힘"
    assert service.apply(pool, "2026202", 3).message == f"막힘: {rules.CLOSED}"


@needs_db
def test_admin_flow_hard_scenario_with_all_models_failing(pool, monkeypatch):
    """키를 틀리게 두어 3차 모델까지 실패시키면, 앱이 스스로 규칙을 지키는 배정을 만들어 확정함."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-invalid-key-for-test")
    service.reset_board(pool, read_sample("어려움"), 4)
    run_steps(pool, HARD)

    at = admin_session()
    assert "admin_confirm" not in keys(at)  # 배정안이 없으면 확정 단추를 보여 주지 않음
    at.button(key="admin_assign").click().run()
    assert result_of(at).startswith("막힘: 먼저 모집을 마감")

    at.button(key="admin_close").click().run()
    assert any(m.value.startswith("승인: 모집을 마감함") for m in at.success)

    at.button(key="admin_assign").click().run()
    assert not at.exception
    assert any(m.value.startswith("승인: 배정안을 만듦(앱이 직접 배정") for m in at.success)
    assert "admin_confirm" in keys(at)

    at.button(key="admin_confirm").click().run()
    assert any(m.value.startswith("승인: 배정안을 확정함") for m in at.success)

    board = service.load_board(pool)
    assert not board.unassigned()
    for team_no, members in board.teams.items():
        assert rules.team_problems(team_no, members) == []

    with pool.connection() as conn:
        logs = conn.execute("select outcome from tf_ai_logs order by id desc limit 3").fetchall()
    assert all("401" in r["outcome"] for r in logs)


@needs_db
def test_admin_flow_reports_impossible_assignment(pool):
    students = [S("9001", PL), S("9002", PL), S("9003", WP), S("9004", FD)]
    service.reset_board(pool, students, 2)
    service.apply(pool, "9001", 1)
    service.apply(pool, "9003", 1)
    service.vote(pool, "9001", "9003", True)
    service.apply(pool, "9002", 2)  # 혼자인 팀이라 마감 때 빠짐

    def log_count():
        with pool.connection() as conn:
            return conn.execute("select count(*) as n from tf_ai_logs").fetchone()["n"]

    before = log_count()
    at = admin_session()
    at.button(key="admin_close").click().run()
    at.button(key="admin_assign").click().run()
    assert result_of(at).count("막힘: 규칙을 지키는 배정이 없음") == 1
    texts = " ".join(m.value for m in at.markdown)
    assert "팀2에 웹 프로그래머를 맡을 학생이 없음" in texts
    assert "admin_confirm" not in keys(at)
    assert log_count() == before  # AI를 부르지 않음
