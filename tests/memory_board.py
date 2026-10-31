"""DB 없이 rules.py의 판단만으로 지원, 투표, 마감을 따라 하는 시험용 게시판.

앱(service.py)과 같은 판단 함수(decide_apply, decide_votes)를 쓰므로,
여기서 시나리오가 통과하면 규칙 판단 자체는 맞다는 뜻임.
"""

import csv
from pathlib import Path

from teamapp import rules
from teamapp.rules import Decision, Student

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load_students(title: str) -> dict[str, Student]:
    with open(SAMPLES / f"{title}.csv", encoding="utf-8-sig", newline="") as f:
        return {
            row["student_no"]: Student(
                row["student_no"],
                row["name"],
                row["main_role"],
                tuple(r for r in row["sub_roles"].split(";") if r),
            )
            for row in csv.DictReader(f)
        }


class MemoryBoard:
    def __init__(self, title: str, team_count: int):
        self.students = load_students(title)
        self.teams: dict[int, list[Student]] = {n: [] for n in range(1, team_count + 1)}
        self.pending: dict[str, tuple[int, dict[str, str]]] = {}  # 지원자 학번 -> (팀, 투표)
        self.closed = False

    def team_of(self, student_no: str) -> int | None:
        for team_no, members in self.teams.items():
            if any(m.student_no == student_no for m in members):
                return team_no
        return None

    def apply(self, student_no: str, team_no: int) -> Decision:
        applicant = self.students[student_no]
        decision = rules.decide_apply(
            closed=self.closed,
            has_team=self.team_of(student_no) is not None,
            has_pending=student_no in self.pending,
            members=self.teams[team_no],
            applicant=applicant,
        )
        if decision.status == rules.APPROVED:
            self.teams[team_no].append(applicant)
        elif decision.status == rules.PENDING:
            self.pending[student_no] = (team_no, {})
        return decision

    def vote(self, voter_no: str, applicant_no: str, yes: bool) -> Decision:
        team_no, votes = self.pending[applicant_no]
        assert self.team_of(voter_no) == team_no, "팀원만 투표할 수 있음"
        assert voter_no not in votes, "한 번 투표하면 바꿀 수 없음"
        votes[voter_no] = "찬성" if yes else "거부"
        decision = rules.decide_votes(self.teams[team_no], self.students[applicant_no], votes)
        if decision.status != rules.PENDING:
            del self.pending[applicant_no]
        if decision.status == rules.APPROVED:
            self.teams[team_no].append(self.students[applicant_no])
        return decision

    def close(self) -> list[str]:
        """모집 마감: 대기 지원은 거절, 1명뿐인 팀의 학생은 팀에서 빠짐. 팀이 없는 학생의 학번을 돌려줌."""
        self.closed = True
        self.pending.clear()
        for team_no, members in self.teams.items():
            if len(members) == 1:
                self.teams[team_no] = []
        return sorted(no for no in self.students if self.team_of(no) is None)

    def unassigned(self) -> list[Student]:
        return [s for no, s in self.students.items() if self.team_of(no) is None]
