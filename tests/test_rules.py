"""2단계 확인: 규칙 판단. 공고 부록의 연습용 시나리오 3개를 단계마다 따라감."""

from teamapp import rules
from teamapp.rules import Assignment, Student

from .memory_board import MemoryBoard


def S(no, main, *subs):
    return Student(no, f"학생{no}", main, subs)


PL, WP, FD, TT, RW, PT = rules.ROLES


def first_word(decision) -> str:
    return decision.message.split(":")[0]


# ---------- 필수 포함 역할 자리 계산(PRD 2.3절, 공고 3장의 예) ----------

def test_one_student_who_can_do_both_fills_only_one():
    assert rules.filled_required([S("1", PL, WP)]) == 1


def test_two_students_fill_both():
    assert rules.filled_required([S("1", PL, WP), S("2", TT, WP)]) == 2


def test_report_writer_blocked_from_tester_presenter_team():
    team = [S("1", TT), S("2", PT)]
    d = rules.decide_apply(closed=False, has_team=False, has_pending=False, members=team, applicant=S("3", RW))
    assert d.message == f"막힘: {rules.SEAT_SHORTAGE}"


def test_sub_role_counts_for_required_role():
    # 주 역할이 테스터이고 보조 역할이 기획자인 학생이 그 팀의 기획자를 맡을 수 있음
    team = [S("1", WP), S("2", FD)]
    d = rules.decide_apply(closed=False, has_team=False, has_pending=False, members=team, applicant=S("3", TT, PL))
    assert first_word(d) == "대기"


def test_block_order_closed_first():
    d = rules.decide_apply(closed=True, has_team=True, has_pending=True, members=[], applicant=S("1", PL))
    assert d.message == f"막힘: {rules.CLOSED}"


def test_full_team_blocked():
    team = [S("1", PL), S("2", WP), S("3", FD), S("4", TT)]
    d = rules.decide_apply(closed=False, has_team=False, has_pending=False, members=team, applicant=S("5", RW))
    assert d.message == f"막힘: {rules.TEAM_FULL}"


def test_vote_reject_is_immediate():
    team = [S("1", PL), S("2", WP)]
    d = rules.decide_votes(team, S("3", FD), {"1": "거부"})
    assert first_word(d) == "거절"


def test_new_member_must_also_vote():
    team = [S("1", PL), S("2", WP)]
    assert first_word(rules.decide_votes(team, S("3", FD), {"1": "찬성"})) == "대기"


# ---------- 연습용 시나리오 1: 쉬움(팀 3개) ----------

def test_practice_easy():
    b = MemoryBoard("쉬움", 3)
    # 1단계
    assert first_word(b.apply("2026101", 1)) == "승인"
    assert first_word(b.apply("2026102", 2)) == "승인"
    assert first_word(b.apply("2026103", 3)) == "승인"
    # 2단계
    assert first_word(b.apply("2026104", 1)) == "대기"
    assert first_word(b.vote("2026101", "2026104", True)) == "승인"
    # 3단계
    assert first_word(b.apply("2026105", 2)) == "대기"
    assert first_word(b.vote("2026102", "2026105", True)) == "승인"
    # 4단계
    assert first_word(b.apply("2026107", 1)) == "대기"
    assert first_word(b.vote("2026101", "2026107", True)) == "대기"
    assert first_word(b.vote("2026104", "2026107", False)) == "거절"
    # 5단계
    assert first_word(b.apply("2026106", 3)) == "대기"
    assert first_word(b.vote("2026103", "2026106", True)) == "승인"
    # 6단계(마감까지. 배정은 4단계 구현에서 시험함)
    assert b.close() == ["2026107", "2026108"]


# ---------- 연습용 시나리오 2: 중간(팀 4개) ----------

def test_practice_medium():
    b = MemoryBoard("중간", 4)
    # 1단계
    assert first_word(b.apply("2026201", 1)) == "승인"
    # 2단계
    assert first_word(b.apply("2026205", 1)) == "대기"
    assert first_word(b.vote("2026201", "2026205", True)) == "승인"
    # 3단계: 주 역할 중복으로 막힘(막힌 지원의 투표는 건너뜀)
    assert b.apply("2026202", 1).message == f"막힘: {rules.SAME_MAIN_ROLE}"
    # 4단계
    assert first_word(b.apply("2026206", 2)) == "승인"
    # 5단계
    assert first_word(b.apply("2026209", 2)) == "대기"
    assert first_word(b.vote("2026206", "2026209", True)) == "승인"
    # 6단계
    assert first_word(b.apply("2026210", 2)) == "대기"
    assert first_word(b.vote("2026206", "2026210", True)) == "대기"
    assert first_word(b.vote("2026209", "2026210", False)) == "거절"
    # 7단계
    assert first_word(b.apply("2026203", 3)) == "승인"
    assert first_word(b.apply("2026211", 4)) == "승인"
    # 8단계
    assert first_word(b.apply("2026212", 4)) == "대기"
    assert b.apply("2026212", 3).message == f"막힘: {rules.HAS_PENDING}"
    # 9단계: 학생12의 대기 지원은 거절, 학생3과 학생11은 팀에서 빠짐
    unassigned = b.close()
    assert "2026212" in unassigned and "2026203" in unassigned and "2026211" in unassigned
    assert len(unassigned) == 8
    # 10단계
    assert b.apply("2026202", 3).message == f"막힘: {rules.CLOSED}"


# ---------- 연습용 시나리오 3: 어려움(팀 4개) ----------

def test_practice_hard():
    b = MemoryBoard("어려움", 4)
    # 1~3단계
    assert first_word(b.apply("2026301", 1)) == "승인"
    assert first_word(b.apply("2026304", 1)) == "대기"
    assert first_word(b.vote("2026301", "2026304", True)) == "승인"
    assert first_word(b.apply("2026307", 1)) == "대기"
    assert first_word(b.vote("2026301", "2026307", True)) == "대기"
    assert first_word(b.vote("2026304", "2026307", True)) == "승인"
    # 4~5단계
    assert first_word(b.apply("2026302", 2)) == "승인"
    assert first_word(b.apply("2026308", 2)) == "대기"
    assert first_word(b.vote("2026302", "2026308", True)) == "승인"
    # 6단계: 둘 다 대기
    assert first_word(b.apply("2026305", 2)) == "대기"
    assert first_word(b.apply("2026306", 2)) == "대기"
    # 7단계: 학생5 승인
    assert first_word(b.vote("2026302", "2026305", True)) == "대기"
    assert first_word(b.vote("2026308", "2026305", True)) == "승인"
    # 8단계: 새 팀원 학생5도 투표해야 하고, 모두 찬성하면 승인 직전 검사로 거절
    assert first_word(b.vote("2026302", "2026306", True)) == "대기"
    assert first_word(b.vote("2026308", "2026306", True)) == "대기"
    d = b.vote("2026305", "2026306", True)
    assert d.message == f"거절: 승인 직전 검사에서 {rules.SAME_MAIN_ROLE}"
    # 9~10단계
    assert first_word(b.apply("2026311", 3)) == "승인"
    assert first_word(b.apply("2026315", 3)) == "대기"
    assert first_word(b.vote("2026311", "2026315", True)) == "승인"
    # 11단계: 필수 포함 역할 자리로 막힘
    assert b.apply("2026314", 3).message == f"막힘: {rules.SEAT_SHORTAGE}"
    # 12~13단계
    assert first_word(b.apply("2026310", 4)) == "승인"
    assert first_word(b.apply("2026313", 1)) == "대기"
    assert first_word(b.vote("2026301", "2026313", True)) == "대기"
    # 14단계: 학생13 거절, 학생10은 팀에서 빠짐
    unassigned = b.close()
    assert "2026313" in unassigned and "2026310" in unassigned
    assert len(unassigned) == 8


# ---------- 확정할 팀 구성 검사 다섯 가지 ----------

def make_assignment(proposal):
    teams = {1: [S("1", PL), S("2", WP)], 2: [S("3", PL)]}
    unassigned = [S("4", WP), S("5", FD)]
    return Assignment(teams, unassigned, proposal)


def test_valid_assignment_passes():
    assert rules.validate_assignment(make_assignment([("4", 2), ("5", 1)])) == []


def test_missing_student_fails():
    problems = rules.validate_assignment(make_assignment([("4", 2)]))
    assert any("배정되지 않은 학생" in p for p in problems)


def test_duplicate_student_fails():
    problems = rules.validate_assignment(make_assignment([("4", 2), ("5", 1), ("5", 2)]))
    assert any("두 번 이상" in p for p in problems)


def test_moving_existing_member_fails():
    problems = rules.validate_assignment(make_assignment([("4", 2), ("5", 1), ("1", 2)]))
    assert any("이미 팀에 있는" in p for p in problems)


def test_team_without_web_programmer_fails():
    problems = rules.validate_assignment(make_assignment([("4", 1), ("5", 2)]))
    assert any("팀2에 웹 프로그래머를 맡을 학생이 없음" in p for p in problems)


def test_same_main_role_fails():
    problems = rules.validate_assignment(make_assignment([("4", 1), ("5", 2)]))
    assert any("팀1에 주 역할 웹 프로그래머" in p for p in problems)
