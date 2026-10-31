"""DB에 기록하는 동작(처음 상태 만들기, 지원, 투표, 마감)과 화면에 그릴 상태 읽기.

판단은 rules.py에 맡기고, 여기서는 트랜잭션 안에서 상태를 읽고 결과를 기록함.
같은 팀에 대한 동작은 팀 행을 잠가(for update) 차례로 처리하고,
그래도 같은 자리에 두 명이 들어가려 하면 tf_members의 유일성 제약이 막음.
"""

import json
from dataclasses import dataclass, field

import psycopg
from psycopg_pool import ConnectionPool

from teamapp import db, rules
from teamapp.rules import Decision, Student

STUDENT_PASSWORD = "1234"
SETTING_CLOSED = "closed"


# ---------- 화면에 그릴 상태 ----------

@dataclass
class PendingApplication:
    id: int
    team_no: int
    applicant: Student
    votes: dict[str, str]  # 투표한 학생의 학번 -> 찬성/거부


@dataclass
class Board:
    closed: bool
    team_names: dict[int, str]
    teams: dict[int, list[Student]]
    students: dict[str, Student]
    pending: list[PendingApplication]
    my_last: dict | None = None  # 로그인한 학생의 가장 최근 지원(status, reason, team_no)
    team_of: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.team_of = {m.student_no: n for n, ms in self.teams.items() for m in ms}

    def pending_of(self, student_no: str) -> PendingApplication | None:
        return next((p for p in self.pending if p.applicant.student_no == student_no), None)

    def unassigned(self) -> list[Student]:
        return [s for no, s in self.students.items() if no not in self.team_of]


BOARD_SQL = """
select json_build_object(
  'closed', coalesce((select value from tf_settings where key = 'closed'), '0'),
  'teams', (select coalesce(json_agg(json_build_object('id', id, 'name', name) order by id), '[]')
            from tf_teams),
  'students', (select coalesce(json_agg(json_build_object(
                  'no', s.student_no, 'name', s.name, 'main', s.main_role,
                  'subs', (select coalesce(json_agg(r.role order by r.role), '[]')
                           from tf_student_sub_roles r where r.student_id = s.id))
                  order by s.student_no), '[]')
               from tf_students s where not s.is_admin),
  'members', (select coalesce(json_agg(json_build_object('team', m.team_id, 'no', s.student_no)
                  order by m.team_id, m.slot_no), '[]')
              from tf_members m join tf_students s on s.id = m.student_id),
  'pending', (select coalesce(json_agg(json_build_object(
                  'id', a.id, 'team', a.team_id, 'no', s.student_no,
                  'votes', (select coalesce(json_object_agg(vs.student_no, v.vote), '{}')
                            from tf_votes v join tf_students vs on vs.id = v.voter_id
                            where v.application_id = a.id))
                  order by a.id), '[]')
              from tf_applications a join tf_students s on s.id = a.student_id
              where a.status = '대기'),
  'mine', (select json_build_object('status', a.status, 'reason', a.reason, 'team', a.team_id)
           from tf_applications a join tf_students s on s.id = a.student_id
           where s.student_no = %(me)s order by a.id desc limit 1)
) as board
"""


def load_board(pool: ConnectionPool, me: str = "") -> Board:
    """화면 하나를 그리는 데 필요한 상태를 질의 한 번으로 읽음."""
    with pool.connection() as conn:
        raw = conn.execute(BOARD_SQL, {"me": me}).fetchone()["board"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    students = {
        s["no"]: Student(s["no"], s["name"], s["main"], tuple(s["subs"])) for s in raw["students"]
    }
    teams = {t["id"]: [] for t in raw["teams"]}
    for m in raw["members"]:
        teams[m["team"]].append(students[m["no"]])
    pending = [
        PendingApplication(p["id"], p["team"], students[p["no"]], dict(p["votes"])) for p in raw["pending"]
    ]
    return Board(
        closed=raw["closed"] == "1",
        team_names={t["id"]: t["name"] for t in raw["teams"]},
        teams=teams,
        students=students,
        pending=pending,
        my_last=raw["mine"],
    )


# ---------- 트랜잭션 안에서 쓰는 읽기 ----------

def _is_closed(conn) -> bool:
    row = conn.execute("select value from tf_settings where key = %s", (SETTING_CLOSED,)).fetchone()
    return bool(row) and row["value"] == "1"


def _student(conn, student_no: str) -> dict | None:
    return conn.execute(
        "select id, student_no, name, main_role, is_admin from tf_students where student_no = %s",
        (student_no,),
    ).fetchone()


def _as_student(conn, row: dict) -> Student:
    subs = conn.execute(
        "select role from tf_student_sub_roles where student_id = %s order by role", (row["id"],)
    ).fetchall()
    return Student(row["student_no"], row["name"], row["main_role"], tuple(s["role"] for s in subs))


def _members(conn, team_no: int) -> list[Student]:
    rows = conn.execute(
        "select s.id, s.student_no, s.name, s.main_role from tf_members m"
        " join tf_students s on s.id = m.student_id where m.team_id = %s order by m.slot_no",
        (team_no,),
    ).fetchall()
    return [_as_student(conn, r) for r in rows]


def _lock_team(conn, team_no: int) -> bool:
    """같은 팀에 대한 지원, 투표를 차례로 처리하려고 팀 행을 잠금."""
    return conn.execute("select id from tf_teams where id = %s for update", (team_no,)).fetchone() is not None


def _add_member(conn, team_no: int, student_id: int) -> None:
    """비어 있는 가장 앞 자리에 넣음. 자리가 없거나 이미 다른 팀이면 유일성 제약이 막음."""
    conn.execute(
        "insert into tf_members (team_id, slot_no, student_id)"
        " select %(team)s, min(slot), %(student)s from generate_series(1, 4) as slot"
        " where slot not in (select slot_no from tf_members where team_id = %(team)s)",
        {"team": team_no, "student": student_id},
    )


# ---------- 관리자: 처음 상태 만들기 ----------

def reset_board(pool: ConnectionPool, students: list[Student], team_count: int) -> Decision:
    """지원, 투표, 팀원, 마감 표시를 모두 지우고 명단의 학생과 빈 팀을 만듦. 관리자 계정은 남김."""
    if team_count < 1:
        return Decision(rules.BLOCKED, "팀 수는 1 이상이어야 함")
    # bcrypt는 느리므로 트랜잭션을 열기 전에 해시를 만들어 둠
    hashes = [db.hash_password(STUDENT_PASSWORD, rounds=10) for _ in students]
    with pool.connection() as conn, conn.transaction():
        conn.execute("delete from tf_votes")
        conn.execute("delete from tf_applications")
        conn.execute("delete from tf_members")
        conn.execute("delete from tf_teams")
        conn.execute("delete from tf_students where not is_admin")  # 보조 역할은 cascade로 지워짐
        conn.execute("delete from tf_settings where key in ('closed', 'proposal')")
        for s, password_hash in zip(students, hashes):
            student_id = conn.execute(
                "insert into tf_students (student_no, name, main_role, password_hash)"
                " values (%s, %s, %s, %s) returning id",
                (s.student_no, s.name, s.main_role, password_hash),
            ).fetchone()["id"]
            for role in s.sub_roles:
                conn.execute(
                    "insert into tf_student_sub_roles (student_id, role) values (%s, %s)", (student_id, role)
                )
        for n in range(1, team_count + 1):
            conn.execute("insert into tf_teams (id, name) values (%s, %s)", (n, f"팀{n}"))
    return Decision(rules.APPROVED, f"학생 {len(students)}명, 팀 {team_count}개로 처음 상태를 만듦")


# ---------- 학생: 지원 ----------

def apply(pool: ConnectionPool, student_no: str, team_no: int) -> Decision:
    try:
        with pool.connection() as conn, conn.transaction():
            if not _lock_team(conn, team_no):
                return Decision(rules.BLOCKED, f"팀{team_no}이(가) 없음")
            me = _student(conn, student_no)
            if me is None or me["is_admin"]:
                return Decision(rules.BLOCKED, "학생 계정만 지원할 수 있음")
            has_team = conn.execute(
                "select 1 from tf_members where student_id = %s", (me["id"],)
            ).fetchone() is not None
            has_pending = conn.execute(
                "select 1 from tf_applications where student_id = %s and status = '대기'", (me["id"],)
            ).fetchone() is not None
            decision = rules.decide_apply(
                closed=_is_closed(conn),
                has_team=has_team,
                has_pending=has_pending,
                members=_members(conn, team_no),
                applicant=_as_student(conn, me),
            )
            if decision.status == rules.APPROVED:
                conn.execute(
                    "insert into tf_applications (team_id, student_id, status, reason, decided_at)"
                    " values (%s, %s, '승인', %s, now())",
                    (team_no, me["id"], decision.reason),
                )
                _add_member(conn, team_no, me["id"])
            elif decision.status == rules.PENDING:
                conn.execute(
                    "insert into tf_applications (team_id, student_id) values (%s, %s)", (team_no, me["id"])
                )
            return decision
    except psycopg.errors.IntegrityError as e:
        # 같은 순간에 들어온 다른 요청이 먼저 기록됨
        if e.diag.constraint_name == "tf_applications_one_pending":
            return Decision(rules.BLOCKED, rules.HAS_PENDING)
        return Decision(rules.BLOCKED, f"{rules.TEAM_FULL}(다른 학생이 먼저 들어감)")


# ---------- 학생: 투표 ----------

def vote(pool: ConnectionPool, voter_no: str, applicant_no: str, yes: bool) -> Decision:
    """투표를 기록하고 그 지원의 지금 상태를 돌려줌."""
    try:
        with pool.connection() as conn, conn.transaction():
            applicant = _student(conn, applicant_no)
            if applicant is None:
                return Decision(rules.BLOCKED, "지원자를 찾을 수 없음")
            app = conn.execute(
                "select id, team_id from tf_applications where student_id = %s and status = '대기'",
                (applicant["id"],),
            ).fetchone()
            if app is None:
                last = conn.execute(
                    "select status, reason from tf_applications where student_id = %s order by id desc limit 1",
                    (applicant["id"],),
                ).fetchone()
                if last is None:
                    return Decision(rules.BLOCKED, "대기 중인 지원이 없음")
                return Decision(last["status"], last["reason"] or "")
            team_no = app["team_id"]
            _lock_team(conn, team_no)
            # 잠금을 기다리는 동안 다른 투표가 결과를 냈을 수 있으므로 다시 읽음
            app = conn.execute(
                "select id, status, reason from tf_applications where id = %s for update", (app["id"],)
            ).fetchone()
            if app["status"] != rules.PENDING:
                return Decision(app["status"], app["reason"] or "")
            if _is_closed(conn):
                return Decision(rules.BLOCKED, rules.CLOSED)
            voter = _student(conn, voter_no)
            members = _members(conn, team_no)
            if voter is None or voter_no not in {m.student_no for m in members}:
                return Decision(rules.BLOCKED, f"팀{team_no}의 팀원만 투표할 수 있음")
            already = conn.execute(
                "select vote from tf_votes where application_id = %s and voter_id = %s", (app["id"], voter["id"])
            ).fetchone()
            if already:
                return Decision(rules.BLOCKED, f"이미 투표함(내 투표: {already['vote']})")
            conn.execute(
                "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)",
                (app["id"], voter["id"], "찬성" if yes else "거부"),
            )
            votes = {
                r["student_no"]: r["vote"]
                for r in conn.execute(
                    "select s.student_no, v.vote from tf_votes v join tf_students s on s.id = v.voter_id"
                    " where v.application_id = %s",
                    (app["id"],),
                ).fetchall()
            }
            decision = rules.decide_votes(members, _as_student(conn, applicant), votes)
            if decision.status != rules.PENDING:
                conn.execute(
                    "update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
                    (decision.status, decision.reason, app["id"]),
                )
            if decision.status == rules.APPROVED:
                _add_member(conn, team_no, applicant["id"])
            return decision
    except psycopg.errors.IntegrityError:
        return Decision(rules.REJECTED, f"{rules.TEAM_FULL}(다른 학생이 먼저 들어감)")
