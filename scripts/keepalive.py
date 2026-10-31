"""Supabase가 일시정지되지 않도록 DB에 질의를 보냄(공고 3장 "DB 일시정지"의 어려운 해결).

깃허브 Actions가 매일 한 번 실행함(.github/workflows/keepalive.yml).
DB 주소는 깃허브 저장소의 Secrets(DATABASE_URL)에서 환경 변수로 받으며, 출력하지 않음.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg

KST = timezone(timedelta(hours=9))


def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL: 없음")
        return 1
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    try:
        with psycopg.connect(url, connect_timeout=20, prepare_threshold=None) as conn:
            students = conn.execute("select count(*) from tf_students").fetchone()[0]
            conn.execute(
                "insert into tf_settings (key, value) values ('keepalive_at', %s)"
                " on conflict (key) do update set value = excluded.value",
                (now,),
            )
    except psycopg.Error as e:
        print(f"DB 질의 실패: {type(e).__name__}")
        return 1
    print(f"DB 질의 성공: {now}, 계정 {students}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
