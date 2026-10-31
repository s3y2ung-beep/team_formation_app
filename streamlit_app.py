"""팀 프로젝트 팀 편성 웹 앱(Streamlit).

화면 요소의 key는 공고 2.7절의 표를 그대로 따름. 자동 채점 프로그램이 key로 요소를 찾기 때문임.
단추의 동작은 on_click 콜백에서 처리함. 콜백은 화면을 그리기 전에 실행되므로,
같은 실행에서 바뀐 상태와 결과 안내(result)가 바로 보임.
"""

import time

import streamlit as st

from teamapp import ai, config, db, roster, rules, service, solver

st.set_page_config(page_title="팀 편성", page_icon="👥", layout="wide")

REFRESH_SECONDS = 3  # 다른 사람의 변경을 다시 그리는 간격(공고: 5초 이하)


@st.cache_resource(show_spinner="DB에 연결하는 중")
def get_pool():
    """연결 풀을 앱 전체에서 한 번만 만들고, 테이블과 관리자 계정을 준비함."""
    pool = db.make_pool(config.get_secret("DATABASE_URL"))
    db.apply_schema(pool)
    db.ensure_admin(pool, config.get_secret("ADMIN_PASSWORD"))
    return pool


# ---------- 결과 안내(result) ----------

def set_result(message: str) -> None:
    """단추를 누른 결과를 저장함. 안내는 승인, 대기, 거절, 막힘 가운데 하나로 시작함."""
    st.session_state["result_message"] = message


def show_result() -> None:
    with st.container(key="result"):
        message = st.session_state.get("result_message")
        if not message:
            return
        if message.startswith("승인"):
            st.success(message)
        elif message.startswith("대기"):
            st.info(message)
        else:
            st.error(message)


# ---------- 공통 표시 ----------

def student_line(s: rules.Student) -> str:
    subs = ", ".join(s.sub_roles) if s.sub_roles else "없음"
    return f"**{s.name}** · 주 역할 {s.main_role} · 보조 역할 {subs}"


def team_card(board: service.Board, team_no: int, my_team: int | None = None) -> None:
    """팀 하나의 표시(key: team_N). 팀원의 이름과 주 역할, 보조 역할을 보여 줌."""
    members = board.teams[team_no]
    with st.container(key=f"team_{team_no}", border=True):
        mark = " · 🟢 내 팀" if team_no == my_team else ""
        st.markdown(f"#### {board.team_names[team_no]}{mark}  \n{len(members)}/{rules.MAX_TEAM}명")
        if members:
            for m in members:
                st.markdown(f"- {student_line(m)}")
        else:
            st.caption("아직 팀원이 없음")
        waiting = [p for p in board.pending if p.team_no == team_no]
        if waiting:
            st.caption("지원 대기: " + ", ".join(p.applicant.name for p in waiting))


def grid(items: list, columns: int = 2):
    """항목을 columns개씩 나란히 놓을 열을 차례로 돌려줌."""
    cols = st.columns(columns)
    for i, item in enumerate(items):
        yield cols[i % columns], item


# ---------- 로그인 ----------

def current_user(pool) -> dict | None:
    """세션에 기록한 학번으로 계정을 다시 읽음. 명단을 다시 올려 계정이 없어졌으면 로그아웃함."""
    student_no = st.session_state.get("user_no")
    if not student_no:
        return None
    user = db.find_user(pool, student_no)
    if user is None:
        st.session_state.pop("user_no", None)
    return user


def login_view(pool) -> None:
    st.title("👥 팀 프로젝트 팀 편성")
    with st.form("login_form"):
        student_no = st.text_input("학번", key="login_student_no")
        password = st.text_input("비밀번호", type="password", key="login_password")
        submitted = st.form_submit_button("로그인", key="login_submit")
    if submitted:
        user = db.verify_login(pool, student_no, password)
        if user is None:
            set_result("막힘: 학번 또는 비밀번호가 틀림")
        else:
            st.session_state["user_no"] = user["student_no"]
            set_result(f"승인: {user['name']}(으)로 로그인함")
            st.rerun()
    show_result()


def role_text(user: dict) -> str:
    if user["is_admin"]:
        return "관리자"
    subs = ", ".join(user["sub_roles"]) or "없음"
    return f"주 역할 {user['main_role']} · 보조 역할 {subs}"


def header(user: dict) -> None:
    left, right = st.columns([5, 1])
    with left:
        with st.container(key="whoami"):
            st.markdown(f"**{user['name']}** ({user['student_no']}) · {role_text(user)}")
    with right:
        if st.button("로그아웃", key="logout"):
            st.session_state.clear()
            st.rerun()


# ---------- 학생 화면 ----------

def on_apply(student_no: str, team_no: int) -> None:
    decision = service.apply(get_pool(), student_no, team_no)
    set_result(f"{decision.message} (팀{team_no} 지원)")


def on_vote(voter_no: str, applicant_no: str, applicant_name: str, yes: bool) -> None:
    decision = service.vote(get_pool(), voter_no, applicant_no, yes)
    choice = "찬성" if yes else "거부"
    set_result(f"{decision.message} ({applicant_name}의 지원에 {choice})")


def my_status_text(board: service.Board, me: str) -> str:
    team_no = board.team_of.get(me)
    if team_no:
        return f"내 팀: {board.team_names[team_no]}"
    pending = board.pending_of(me)
    if pending:
        voted = sum(1 for v in pending.votes.values() if v == "찬성")
        total = len(board.teams[pending.team_no])
        return f"아직 팀이 없음 · {board.team_names[pending.team_no]}에 지원함(대기, 찬성 {voted}/{total})"
    last = board.my_last
    if last and last["status"] == rules.REJECTED:
        return f"아직 팀이 없음 · 지난 지원은 거절됨({last['reason']})"
    return "아직 팀이 없음"


@st.fragment(run_every=REFRESH_SECONDS)
def student_board(me: str) -> None:
    """학생 화면의 바뀌는 부분. 3초마다 이 부분만 다시 그려 다른 사람의 지원과 투표를 보여 줌."""
    board = service.load_board(get_pool(), me)
    show_result()
    my_team = board.team_of.get(me)
    my_pending = board.pending_of(me)
    can_apply = not board.closed and my_team is None and my_pending is None

    st.markdown(f"**{my_status_text(board, me)}**" + ("  · 🔒 모집이 마감됨" if board.closed else ""))

    st.subheader("팀 목록")
    for col, team_no in grid(sorted(board.teams)):
        with col:
            team_card(board, team_no, my_team)
            st.button(
                f"{board.team_names[team_no]}에 지원",
                key=f"apply_{team_no}",
                disabled=not can_apply,
                on_click=on_apply,
                args=(me, team_no),
                width="stretch",
            )

    if my_team is not None:
        st.subheader("내 팀에 들어온 지원")
        incoming = [p for p in board.pending if p.team_no == my_team]
        if not incoming:
            st.caption("대기 중인 지원이 없음")
        for p in incoming:
            with st.container(border=True):
                yes_count = sum(1 for v in p.votes.values() if v == "찬성")
                st.markdown(f"{student_line(p.applicant)}  \n찬성 {yes_count}/{len(board.teams[my_team])}")
                my_vote = p.votes.get(me)
                if my_vote:
                    st.markdown(f"내 투표: {my_vote}")
                elif not board.closed:
                    no = p.applicant.student_no
                    yes_col, no_col = st.columns(2)
                    yes_col.button(
                        "찬성", key=f"vote_yes_{no}", on_click=on_vote,
                        args=(me, no, p.applicant.name, True), width="stretch",
                    )
                    no_col.button(
                        "거부", key=f"vote_no_{no}", on_click=on_vote,
                        args=(me, no, p.applicant.name, False), width="stretch",
                    )


def student_view(user: dict) -> None:
    st.title("학생 화면")
    student_board(user["student_no"])


# ---------- 관리자 화면 ----------

def require_admin() -> bool:
    """관리자 기능은 화면이 아니라 서버에서 다시 확인함(학생 계정으로 쓸 수 없게)."""
    user = db.find_user(get_pool(), st.session_state.get("user_no", ""))
    if user is None or not user["is_admin"]:
        set_result("막힘: 관리자만 할 수 있음")
        return False
    return True


def on_start() -> None:
    if not require_admin():
        return
    uploaded = st.session_state.get("admin_roster_file")
    if uploaded is None:
        set_result("막힘: 명단 CSV 파일을 올리지 않음")
        return
    try:
        students = roster.parse_roster(uploaded.getvalue())
    except roster.RosterError as e:
        set_result(f"막힘: 명단 파일이 틀림({e})")
        return
    team_count = int(st.session_state.get("admin_team_count") or 0)
    set_result(service.reset_board(get_pool(), students, team_count).message)
    st.session_state.pop("assign_report", None)


def on_close() -> None:
    if require_admin():
        set_result(service.close_recruitment(get_pool()).message)


def on_confirm() -> None:
    if require_admin():
        set_result(service.confirm_proposal(get_pool()).message)
        st.session_state.pop("assign_report", None)


@st.fragment(run_every=REFRESH_SECONDS)
def admin_board() -> None:
    """관리자 화면의 바뀌는 부분(팀이 없는 학생, 팀 목록)."""
    board = service.load_board(get_pool())
    st.markdown(
        f"학생 {len(board.students)}명 · 팀 {len(board.teams)}개 · 대기 중인 지원 {len(board.pending)}건"
        + (" · 🔒 모집이 마감됨" if board.closed else " · 모집 중")
    )
    st.subheader("팀이 없는 학생")
    with st.container(key="unassigned", border=True):
        left = board.unassigned()
        if left:
            for s in left:
                st.markdown(f"- {student_line(s)}")
        else:
            st.caption("팀이 없는 학생이 없음")
    st.subheader("팀 목록")
    for col, team_no in grid(sorted(board.teams)):
        with col:
            team_card(board, team_no)


def proposal_table(board: service.Board, proposal: list[tuple[str, int]]) -> None:
    rows = []
    for student_no, team_no in proposal:
        s = board.students.get(student_no)
        rows.append({
            "이름": s.name if s else student_no,
            "주 역할": s.main_role if s else "",
            "보조 역할": ", ".join(s.sub_roles) if s and s.sub_roles else "없음",
            "배정된 팀": board.team_names.get(team_no, f"팀{team_no}"),
        })
    st.dataframe(rows, hide_index=True, width="stretch")


def attempts_table(attempts: list[dict]) -> None:
    if attempts:
        st.markdown("**모델별 시도 결과**")
        st.dataframe(attempts, hide_index=True, width="stretch")


def run_ai_assign(status_box) -> None:
    """AI 배정. 기다리는 동안 몇 차 모델의 응답을 기다리는지 assign_status에 보여 줌."""
    pool = get_pool()
    service.clear_proposal(pool)
    st.session_state.pop("assign_report", None)
    board = service.load_board(pool)
    if not board.closed:
        set_result("막힘: 먼저 모집을 마감해야 함")
        return
    unassigned = board.unassigned()

    # 1. 규칙을 지키는 배정이 있는지 모든 경우를 따져 먼저 확인함. 없으면 AI를 부르지 않음
    if solver.find_assignment(board.teams, unassigned) is None:
        reasons = solver.explain_impossible(board.teams, unassigned)
        st.session_state["assign_report"] = {"impossible": reasons}
        set_result("막힘: 규칙을 지키는 배정이 없음")
        return
    if not unassigned:
        set_result("막힘: 팀이 없는 학생이 없어 배정할 것이 없음")
        return

    # 2. 1차, 2차, 3차 모델을 차례로 부름
    run_id = time.strftime("%Y%m%d-%H%M%S")
    with status_box:
        progress = st.empty()
        done_box = st.container()

    def on_progress(order: int, model: str, elapsed: float) -> None:
        progress.info(
            f"⏳ {order}차 모델 응답 기다리는 중: `{model}` · {elapsed:.0f}초 경과 / {ai.MODEL_TIMEOUT}초"
        )

    def on_attempt(a: ai.Attempt) -> None:
        service.log_attempt(pool, run_id, a.order, a.model, a.outcome, a.elapsed)
        icon = "✅" if a.outcome == "성공" else "❌"
        done_box.markdown(f"{icon} {a.order}차 `{a.model}`: {a.outcome} ({a.elapsed:.0f}초)")

    result = ai.run_assignment(
        board.teams, unassigned, config.get_secret("OPENROUTER_API_KEY"),
        on_progress=on_progress, on_attempt=on_attempt,
    )
    progress.empty()
    attempts = [
        {"차례": f"{a.order}차", "모델": a.model, "결과": a.outcome, "걸린 시간(초)": a.elapsed}
        for a in result.attempts
    ]
    if not result.proposal:
        st.session_state["assign_report"] = {"attempts": attempts}
        set_result("막힘: 배정안을 만들지 못함")
        return
    service.save_proposal(pool, result.proposal, result.source)
    st.session_state["assign_report"] = {"attempts": attempts}
    set_result(f"승인: 배정안을 만듦({result.source}). 확인한 뒤 확정을 누름")


def show_assign_report(status_box) -> None:
    """마지막 AI 배정의 결과를 assign_status 안에 보여 줌."""
    report = st.session_state.get("assign_report") or {}
    saved = service.load_proposal(get_pool())
    with status_box:
        if report.get("impossible"):
            st.error("규칙을 지키는 배정이 없음")
            for reason in report["impossible"]:
                st.markdown(f"- {reason}")
            st.caption("이때는 AI를 부르지 않음")
        attempts_table(report.get("attempts", []))
        if saved:
            st.success(f"배정안(배정안을 낸 곳: {saved['source']}). 다섯 가지 검사를 통과함")
            proposal_table(service.load_board(get_pool()), saved["proposal"])
        elif not report:
            st.caption("모집을 마감한 뒤 AI 배정을 누름. 1차, 2차, 3차 모델이 모두 실패하면 앱이 직접 배정함")


def admin_view() -> None:
    st.title("관리자 화면")
    result_slot = st.container()

    with st.expander("1. 명단으로 처음 상태 만들기", expanded=True):
        st.file_uploader("명단 CSV 파일", type=["csv"], key="admin_roster_file")
        st.number_input("팀 수", min_value=1, max_value=20, value=3, step=1, key="admin_team_count")
        st.button("명단으로 처음 상태 만들기", key="admin_start", on_click=on_start, type="primary")
        st.caption("누르면 지원, 투표, 팀원, 마감 표시가 모두 지워짐. 관리자 계정은 남음")

    st.subheader("2. 모집 마감과 AI 배정")
    c1, c2 = st.columns(2)
    c1.button("모집 마감", key="admin_close", on_click=on_close, width="stretch")
    assign_clicked = c2.button("AI 배정", key="admin_assign", width="stretch")
    status_box = st.container(key="assign_status", border=True)
    if assign_clicked and require_admin():
        run_ai_assign(status_box)
    show_assign_report(status_box)
    # 확정 단추는 검사를 통과한 배정안이 있을 때만 보여 줌(AI를 기다리는 동안 누를 수 없게)
    if service.load_proposal(get_pool()):
        st.button("배정안 확정", key="admin_confirm", on_click=on_confirm, type="primary", width="stretch")

    # 결과 안내는 AI 배정처럼 이 실행 안에서 끝나는 동작의 결과까지 담도록 맨 마지막에 채움
    with result_slot:
        show_result()

    admin_board()


def main() -> None:
    if not config.get_secret("DATABASE_URL") or not config.get_secret("ADMIN_PASSWORD"):
        status = config.secret_status()
        st.error(
            "설정이 모자라 앱을 시작할 수 없음 "
            f"(DATABASE_URL: {status['DATABASE_URL']}, ADMIN_PASSWORD: {status['ADMIN_PASSWORD']})"
        )
        st.stop()
    pool = get_pool()
    user = current_user(pool)
    if user is None:
        login_view(pool)
        return
    header(user)
    if user["is_admin"]:
        admin_view()
    else:
        student_view(user)


main()
