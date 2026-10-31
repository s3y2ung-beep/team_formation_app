"""명단 CSV 읽기와 검사(PRD 3.2절).

형식: student_no,name,main_role,sub_roles. 보조 역할 2개는 ;로 구분하고, 없으면 마지막 쉼표 뒤를 비워 둠.
나눠 주는 파일은 BOM이 붙은 UTF-8이므로 utf-8-sig로 읽음.
"""

import csv
import io

from teamapp.db import ADMIN_NO
from teamapp.rules import ROLES, Student

COLUMNS = ["student_no", "name", "main_role", "sub_roles"]
MAX_SUB_ROLES = 2


class RosterError(ValueError):
    pass


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # 엑셀에서 "CSV(쉼표로 분리)"로 다시 저장하면 CP949가 되기도 함
        try:
            return data.decode("cp949")
        except UnicodeDecodeError:
            raise RosterError("파일을 UTF-8로 읽을 수 없음") from None


def parse_roster(data: bytes) -> list[Student]:
    rows = list(csv.reader(io.StringIO(decode(data))))
    rows = [r for r in rows if any(cell.strip() for cell in r)]  # 빈 줄은 건너뜀
    if not rows:
        raise RosterError("파일이 비어 있음")
    header = [h.strip() for h in rows[0]]
    if header != COLUMNS:
        raise RosterError("첫 줄이 " + ",".join(COLUMNS) + " 이어야 함")

    students: list[Student] = []
    seen: set[str] = set()
    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) != len(COLUMNS):
            raise RosterError(f"{line_no}번째 줄의 열이 {len(row)}개임(4개여야 함)")
        student_no, name, main_role, sub_text = (cell.strip() for cell in row)
        if not student_no or not name:
            raise RosterError(f"{line_no}번째 줄에 학번이나 이름이 비어 있음")
        if student_no.lower() == ADMIN_NO:
            raise RosterError(f"{line_no}번째 줄의 학번 {student_no}은(는) 관리자 학번이라 쓸 수 없음")
        if student_no in seen:
            raise RosterError(f"학번 {student_no}이(가) 두 번 나옴")
        if main_role not in ROLES:
            raise RosterError(f"{line_no}번째 줄의 주 역할 '{main_role}'은(는) 6개 역할에 없음")
        subs = [s.strip() for s in sub_text.split(";") if s.strip()]
        if len(subs) > MAX_SUB_ROLES:
            raise RosterError(f"{line_no}번째 줄의 보조 역할이 {len(subs)}개임(0~2개여야 함)")
        for sub in subs:
            if sub not in ROLES:
                raise RosterError(f"{line_no}번째 줄의 보조 역할 '{sub}'은(는) 6개 역할에 없음")
        if main_role in subs or len(set(subs)) != len(subs):
            raise RosterError(f"{line_no}번째 줄의 역할이 겹침")
        seen.add(student_no)
        students.append(Student(student_no, name, main_role, tuple(subs)))

    if not students:
        raise RosterError("학생이 한 명도 없음")
    return students
