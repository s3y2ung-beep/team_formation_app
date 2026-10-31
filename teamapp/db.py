"""DB 연결과 계정 관련 질의.

연결 풀은 앱 전체에서 한 번만 만들고 다시 씀(공고 4.2절).
잠든 앱이 깨어나면 풀 안의 연결이 끊겨 있을 수 있으므로, 꺼낼 때마다 확인하고 끊겼으면 새로 만듦.
"""

from pathlib import Path

import bcrypt
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

ADMIN_NO = "admin"
ADMIN_NAME = "관리자"


def normalize_url(url: str) -> str:
    """SQLAlchemy 꼴 주소(postgresql+psycopg://)도 받아들이게 앞머리를 고침."""
    url = url.strip()
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def make_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo=normalize_url(database_url),
        min_size=1,
        max_size=5,
        timeout=20,
        # 꺼낼 때 연결이 살아 있는지 확인하고, 죽었으면 버리고 새로 만듦
        check=ConnectionPool.check_connection,
        kwargs={
            "row_factory": dict_row,
            # Supabase 풀러(Transaction 모드)는 준비된 질의를 지원하지 않으므로 끔
            "prepare_threshold": None,
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            # 응답 없는 연결을 10분이 아니라 8초 안에 알아챔
            "tcp_user_timeout": 8000,
        },
        open=True,
    )


def apply_schema(pool: ConnectionPool) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with pool.connection() as conn:
        conn.execute(sql)


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def ensure_admin(pool: ConnectionPool, admin_password: str) -> None:
    """관리자 계정을 만들거나, 비밀번호가 바뀌었으면 해시를 갱신함."""
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD가 없음")
    with pool.connection() as conn:
        row = conn.execute(
            "select id, password_hash from tf_students where student_no = %s", (ADMIN_NO,)
        ).fetchone()
        if row is None:
            conn.execute(
                "insert into tf_students (student_no, name, main_role, password_hash, is_admin)"
                " values (%s, %s, null, %s, true)",
                (ADMIN_NO, ADMIN_NAME, hash_password(admin_password)),
            )
        elif not check_password(admin_password, row["password_hash"]):
            conn.execute(
                "update tf_students set password_hash = %s, is_admin = true where id = %s",
                (hash_password(admin_password), row["id"]),
            )


def find_user(pool: ConnectionPool, student_no: str) -> dict | None:
    """학번으로 계정을 찾음. 보조 역할 목록을 sub_roles로 붙여 돌려줌."""
    with pool.connection() as conn:
        row = conn.execute(
            "select id, student_no, name, main_role, password_hash, is_admin"
            " from tf_students where student_no = %s",
            (student_no.strip(),),
        ).fetchone()
        if row is None:
            return None
        subs = conn.execute(
            "select role from tf_student_sub_roles where student_id = %s order by role",
            (row["id"],),
        ).fetchall()
    row["sub_roles"] = [s["role"] for s in subs]
    return row


def verify_login(pool: ConnectionPool, student_no: str, password: str) -> dict | None:
    """학번과 비밀번호가 맞으면 계정을, 아니면 None을 돌려줌."""
    user = find_user(pool, student_no)
    if user is None or not check_password(password, user["password_hash"]):
        return None
    return user
