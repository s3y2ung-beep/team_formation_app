"""팀 규칙 검사(PRD 2장). 화면과 DB를 모르는 순수 파이썬이라 자동 시험으로 확인함.

- 주 역할은 팀 안의 중복을 따지는 기준이고, 보조 역할은 필수 포함 역할을 맡을 수 있는지 따질 때만 씀
- 판단 결과는 Decision으로 돌려주며, 안내 문구는 "승인", "대기", "거절", "막힘" 가운데 하나로 시작함
"""

from dataclasses import dataclass, field

ROLES = ("기획자", "웹 프로그래머", "프론트엔드 디자이너", "테스터", "보고서 작성자", "발표자")
PLANNER = "기획자"
WEB = "웹 프로그래머"
REQUIRED_ROLES = (PLANNER, WEB)

MIN_TEAM = 2
MAX_TEAM = 4

APPROVED, PENDING, REJECTED, BLOCKED = "승인", "대기", "거절", "막힘"

# 막힘 이유(PRD 2.6절). 화면 안내와 시험이 같은 문구를 씀
CLOSED = "모집이 마감됨"
HAS_TEAM = "이미 팀이 있음"
HAS_PENDING = "결과를 기다리는 지원이 있음"
TEAM_FULL = "팀이 꽉 참"
SAME_MAIN_ROLE = "같은 주 역할의 팀원이 있음"
SEAT_SHORTAGE = "필수 포함 역할을 맡을 학생의 자리가 모자람"


@dataclass(frozen=True)
class Student:
    student_no: str
    name: str
    main_role: str
    sub_roles: tuple[str, ...] = ()

    def can(self, role: str) -> bool:
        """그 역할을 맡을 수 있는지(주 역할이나 보조 역할)."""
        return role == self.main_role or role in self.sub_roles


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str = ""

    @property
    def message(self) -> str:
        return f"{self.status}: {self.reason}" if self.reason else self.status


@dataclass
class Assignment:
    """확정할 팀 구성 검사에 쓰는 입력. teams는 팀 번호마다 지금 팀원 목록."""

    teams: dict[int, list[Student]]
    unassigned: list[Student]
    proposal: list[tuple[str, int]] = field(default_factory=list)  # (학번, 팀 번호)


# ---------- 필수 포함 역할 ----------

def filled_required(members: list[Student]) -> int:
    """기획자와 웹 프로그래머를 서로 다른 학생에게 맡길 때 최대로 맡길 수 있는 수(0~2).

    한 학생이 둘 다 할 수 있어도 하나로만 셈(PRD 2.3절).
    """
    planners = [m for m in members if m.can(PLANNER)]
    webs = [m for m in members if m.can(WEB)]
    if any(p != w for p in planners for w in webs):
        return 2
    return 1 if planners or webs else 0


def missing_required_text(members: list[Student]) -> str:
    """필수 포함 역할이 왜 모자라는지 사람이 읽을 문장으로 돌려줌. 모자라지 않으면 빈 문자열."""
    if filled_required(members) == 2:
        return ""
    has_planner = any(m.can(PLANNER) for m in members)
    has_web = any(m.can(WEB) for m in members)
    if not has_planner and not has_web:
        return "기획자와 웹 프로그래머를 맡을 학생이 없음"
    if not has_planner:
        return "기획자를 맡을 학생이 없음"
    if not has_web:
        return "웹 프로그래머를 맡을 학생이 없음"
    return "기획자와 웹 프로그래머를 서로 다른 학생이 맡을 수 없음"


def has_seat_shortage(members_after: list[Student]) -> bool:
    """들어간 뒤 남는 자리가 아직 채우지 못한 필수 포함 역할 수보다 적은지."""
    remaining_seats = MAX_TEAM - len(members_after)
    return remaining_seats < len(REQUIRED_ROLES) - filled_required(members_after)


# ---------- 지원과 투표 ----------

def join_problem(members: list[Student], applicant: Student) -> str:
    """지원자가 이 팀에 들어갈 때 어기는 규칙. 문제가 없으면 빈 문자열.

    지원할 때와 승인 직전 검사(PRD 2.5절)에 똑같이 씀.
    """
    if len(members) >= MAX_TEAM:
        return TEAM_FULL
    if any(m.main_role == applicant.main_role for m in members):
        return SAME_MAIN_ROLE
    if has_seat_shortage([*members, applicant]):
        return SEAT_SHORTAGE
    return ""


def decide_apply(
    *, closed: bool, has_team: bool, has_pending: bool, members: list[Student], applicant: Student
) -> Decision:
    """지원 단추를 누른 순간의 판단. 막힘이면 DB에 기록하지 않음."""
    for blocked, reason in ((closed, CLOSED), (has_team, HAS_TEAM), (has_pending, HAS_PENDING)):
        if blocked:
            return Decision(BLOCKED, reason)
    problem = join_problem(members, applicant)
    if problem:
        return Decision(BLOCKED, problem)
    if not members:
        return Decision(APPROVED, "빈 팀이라 바로 승인됨")
    return Decision(PENDING, f"팀원 {len(members)}명의 투표를 기다림")


def decide_votes(members: list[Student], applicant: Student, votes: dict[str, str]) -> Decision:
    """지금까지의 투표로 지원의 상태를 정함.

    votes는 투표한 학생의 학번 -> "찬성" 또는 "거부". 투표할 사람은 지금의 팀원이며,
    지원한 뒤에 팀원이 된 학생도 투표해야 함. 모두 찬성하면 승인 직전 검사를 함.
    """
    member_votes = [votes.get(m.student_no) for m in members]
    if "거부" in member_votes:
        return Decision(REJECTED, "팀원이 거부함")
    waiting = member_votes.count(None)
    if waiting:
        return Decision(PENDING, f"팀원 {len(members)}명 중 {waiting}명의 투표를 기다림")
    problem = join_problem(members, applicant)
    if problem:
        return Decision(REJECTED, f"승인 직전 검사에서 {problem}")
    return Decision(APPROVED, "팀원 모두 찬성함")


# ---------- 확정할 팀 구성 검사(PRD 3.6절의 다섯 가지) ----------

def team_problems(team_no: int, members: list[Student]) -> list[str]:
    """한 팀이 확정 규칙(인원, 주 역할 중복, 필수 포함 역할)을 어기는 곳."""
    problems = []
    if not MIN_TEAM <= len(members) <= MAX_TEAM:
        problems.append(f"팀{team_no}의 인원이 {len(members)}명임(2~4명이어야 함)")
    mains = [m.main_role for m in members]
    for role in sorted({r for r in mains if mains.count(r) > 1}):
        problems.append(f"팀{team_no}에 주 역할 {role}이(가) 겹침")
    missing = missing_required_text(members)
    if missing:
        problems.append(f"팀{team_no}에 {missing}")
    return problems


def validate_assignment(a: Assignment) -> list[str]:
    """배정안을 다섯 가지로 검사함. 통과하면 빈 목록."""
    problems = []
    unassigned_nos = {s.student_no for s in a.unassigned}
    member_nos = {m.student_no for ms in a.teams.values() for m in ms}

    proposed_nos = [no for no, _ in a.proposal]

    # 1. 팀이 없는 학생이 빠짐없이 배정됨
    missing = [s.name for s in a.unassigned if s.student_no not in proposed_nos]
    if missing:
        problems.append("배정되지 않은 학생이 있음: " + ", ".join(missing))

    # 2. 한 학생은 한 팀에만 배정됨(이미 팀에 있는 학생과 명단 밖 학생은 배정하지 않음)
    for student_no in sorted({no for no in proposed_nos if proposed_nos.count(no) > 1}):
        problems.append(f"학생 {student_no}을(를) 두 번 이상 배정함")
    for student_no, team_no in a.proposal:
        if student_no in member_nos:
            problems.append(f"이미 팀에 있는 학생 {student_no}을(를) 옮기려 함")
        elif student_no not in unassigned_nos:
            problems.append(f"팀이 없는 학생 명단에 없는 학번 {student_no}이(가) 있음")
        if team_no not in a.teams:
            problems.append(f"없는 팀 번호 {team_no}에 배정함")

    if problems:
        return problems

    # 3~5. 배정한 뒤 모든 팀의 인원, 주 역할 중복, 필수 포함 역할
    by_no = {s.student_no: s for s in a.unassigned}
    for team_no, members in sorted(a.teams.items()):
        added = [by_no[no] for no, t in a.proposal if t == team_no]
        problems.extend(team_problems(team_no, [*members, *added]))
    return problems
