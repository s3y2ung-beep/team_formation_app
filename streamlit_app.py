"""팀 프로젝트 팀 편성 웹 앱(Streamlit).

화면 요소의 key는 공고 2.7절의 표를 그대로 따름. 자동 채점 프로그램이 key로 요소를 찾기 때문임.
"""

import streamlit as st

from teamapp import config, db

st.set_page_config(page_title="팀 편성", page_icon="👥", layout="wide")


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


# ---------- 화면 ----------

def admin_view(pool, user: dict) -> None:
    st.title("관리자 화면")
    show_result()
    st.caption("명단 올리기, 모집 마감, AI 배정은 다음 단계에서 만듦")


def student_view(pool, user: dict) -> None:
    st.title("학생 화면")
    show_result()
    st.caption("팀 목록, 지원, 투표는 다음 단계에서 만듦")


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
        admin_view(pool, user)
    else:
        student_view(pool, user)


main()
