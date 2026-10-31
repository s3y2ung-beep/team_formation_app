"""모든 경우를 따져 규칙을 지키는 배정을 찾음(공고 3장 "3차 모델까지 실패"의 어려운 해결).

팀이 없는 학생을 한 명씩 팀에 넣어 보다가, 규칙을 어기게 되거나 끝까지 갈 수 없는 길이면
바로 되돌아감(백트래킹). 빈 팀끼리는 서로 같으므로 빈 팀 중 첫째에만 넣어 봄.
배정이 없으면 None을 돌려주고, explain_impossible()이 그 이유를 만듦.
"""

from teamapp import rules
from teamapp.rules import Student

Proposal = list[tuple[str, int]]


def _team_can_still_work(members: list[Student]) -> bool:
    """더 넣을 수 있는 자리로 필수 포함 역할을 채울 가능성이 남아 있는지."""
    return not rules.has_seat_shortage(members)


def find_assignment(teams: dict[int, list[Student]], unassigned: list[Student]) -> Proposal | None:
    team_nos = sorted(teams)
    current = {n: list(teams[n]) for n in team_nos}

    def fits(student: Student, n: int) -> bool:
        ms = current[n]
        return len(ms) < rules.MAX_TEAM and all(m.main_role != student.main_role for m in ms)

    # 갈 수 있는 팀이 적은 학생부터 넣어야 막다른 길을 빨리 알아챔
    order = sorted(unassigned, key=lambda s: (sum(fits(s, n) for n in team_nos), s.student_no))
    chosen: Proposal = []

    def hopeless(i: int) -> bool:
        rest = order[i:]
        need_people = sum(max(0, rules.MIN_TEAM - len(current[n])) for n in team_nos)
        if need_people > len(rest):
            return True
        if any(not _team_can_still_work(current[n]) for n in team_nos):
            return True
        # 그 역할이 아직 없는 팀 수가, 남은 학생 중 그 역할을 맡을 수 있는 학생 수보다 많으면 끝까지 가도 안 됨
        for role in rules.REQUIRED_ROLES:
            lacking = sum(1 for n in team_nos if not any(m.can(role) for m in current[n]))
            if lacking > sum(1 for s in rest if s.can(role)):
                return True
        return False

    def search(i: int) -> bool:
        if i == len(order):
            return all(not rules.team_problems(n, current[n]) for n in team_nos)
        if hopeless(i):
            return False
        student = order[i]
        tried_empty = False
        for n in team_nos:
            if not fits(student, n):
                continue
            if not current[n]:
                if tried_empty:
                    continue
                tried_empty = True
            current[n].append(student)
            chosen.append((student.student_no, n))
            if search(i + 1):
                return True
            current[n].pop()
            chosen.pop()
        return False

    if not search(0):
        return None
    return sorted(chosen, key=lambda pair: (pair[1], pair[0]))


def explain_impossible(teams: dict[int, list[Student]], unassigned: list[Student]) -> list[str]:
    """규칙을 지키는 배정이 없을 때 그 이유를 사람이 읽을 문장으로 만듦."""
    reasons = []
    team_nos = sorted(teams)
    left = len(unassigned)

    for n in team_nos:
        members = teams[n]
        candidates = [s for s in unassigned if all(m.main_role != s.main_role for m in members)]
        if len(members) >= rules.MAX_TEAM or rules.has_seat_shortage(members):
            missing = rules.missing_required_text(members)
            if missing:
                reasons.append(f"팀{n}에 {missing}(남은 자리 {rules.MAX_TEAM - len(members)}개로 채울 수 없음)")
            continue
        for role in rules.REQUIRED_ROLES:
            if not any(m.can(role) for m in members) and not any(s.can(role) for s in candidates):
                reasons.append(f"팀{n}에 {role}를 맡을 학생이 없음(팀이 없는 학생 중에도 없음)")

    seats = sum(max(0, rules.MAX_TEAM - len(teams[n])) for n in team_nos)
    if left > seats:
        reasons.append(f"팀이 없는 학생 {left}명이 남은 자리 {seats}개보다 많음")
    need_people = sum(max(0, rules.MIN_TEAM - len(teams[n])) for n in team_nos)
    if need_people > left:
        reasons.append(f"모든 팀을 2명 이상으로 채우려면 {need_people}명이 필요한데 팀이 없는 학생은 {left}명임")

    for role in rules.REQUIRED_ROLES:
        teams_needing = [n for n in team_nos if not any(m.can(role) for m in teams[n])]
        able = [s for s in unassigned if s.can(role)]
        if len(teams_needing) > len(able):
            names = ", ".join(f"팀{n}" for n in teams_needing)
            reasons.append(f"{role}가 필요한 팀은 {len(teams_needing)}개({names})인데 맡을 수 있는 학생은 {len(able)}명임")

    if not reasons:
        reasons.append("팀이 없는 학생을 어떻게 나눠도 모든 팀의 인원, 주 역할, 필수 포함 역할 규칙을 함께 지킬 수 없음")
    return reasons
