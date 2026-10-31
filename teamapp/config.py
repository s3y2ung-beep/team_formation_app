"""비밀 값 읽기.

내 PC에서는 .env 파일에서, 배포한 앱에서는 Streamlit Secrets에서 읽음.
값 자체는 어디에도 출력하지 않음. 있는지 확인할 때는 secret_status()로 "있음, 없음"만 봄.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

SECRET_NAMES = ("OPENROUTER_API_KEY", "DATABASE_URL", "ADMIN_PASSWORD")

# .env는 앱 파일과 같은 폴더(저장소 맨 위)에 있음. 이미 있는 환경 변수는 덮어쓰지 않음
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_secret(name: str) -> str:
    """환경 변수(.env 포함)를 먼저 보고, 없으면 Streamlit Secrets를 봄. 둘 다 없으면 빈 문자열."""
    value = os.getenv(name, "")
    if value:
        return value.strip()
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        # secrets.toml이 없는 내 PC에서는 st.secrets를 읽을 때 오류가 남. 없음으로 처리함
        pass
    return ""


def secret_status() -> dict[str, str]:
    """비밀 값마다 "있음" 또는 "없음"만 돌려줌."""
    return {name: ("있음" if get_secret(name) else "없음") for name in SECRET_NAMES}
