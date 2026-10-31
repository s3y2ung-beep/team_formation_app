"""AI 배정(PRD 3.6절). 오픈라우터의 무료 모델 3개를 1차, 2차, 3차로 차례로 부름.

- 모델 하나를 부른 때부터 응답을 다 받을 때까지 전체 시간을 재서 120초가 넘으면 끊고 다음 모델로 넘어감.
  요청은 별도 스레드에서 보내고, 화면 쪽은 1초마다 경과 시간을 받아 안내를 고침
- 빈 응답, HTTP 오류(429 등), JSON이 아닌 응답, 다섯 가지 검사 불통과를 모두 실패로 처리함
- 3차까지 실패하면 solver.py가 모든 경우를 따져 배정함
- API 키는 요청 머리글에만 넣고 화면, 로그, 오류 문구에 남기지 않음
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Callable

import requests

from teamapp import rules, solver
from teamapp.rules import Assignment, Student

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = (
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
)
MODEL_TIMEOUT = 120  # 모델 하나에 주는 전체 대기 시간(초)
MAX_TOKENS = 8000

# 시간이 넘은 요청은 기다리지 않고 버리므로, 스레드가 남아도 화면은 다음 모델로 넘어감
_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="openrouter")


@dataclass
class Attempt:
    order: int  # 몇 차 모델인지
    model: str
    outcome: str  # "성공" 또는 실패 이유
    elapsed: float


@dataclass
class AssignResult:
    proposal: list[tuple[str, int]]
    source: str  # 배정안을 낸 곳
    attempts: list[Attempt] = field(default_factory=list)


class ModelFailure(Exception):
    pass


# ---------- 프롬프트와 응답 읽기 ----------

def _describe(s: Student) -> dict:
    return {"student_no": s.student_no, "name": s.name, "main_role": s.main_role, "sub_roles": list(s.sub_roles)}


def build_prompt(teams: dict[int, list[Student]], unassigned: list[Student]) -> str:
    data = {
        "teams": [{"team": n, "members": [_describe(m) for m in ms]} for n, ms in sorted(teams.items())],
        "unassigned_students": [_describe(s) for s in unassigned],
    }
    return (
        "팀 프로젝트의 팀 편성을 마무리해야 합니다. 팀이 없는 학생(unassigned_students)을 모두 팀에 배정하세요.\n\n"
        "규칙\n"
        "1. 팀이 없는 학생은 빠짐없이, 한 명당 한 팀에만 배정함\n"
        "2. 이미 팀에 있는 학생(members)은 옮기지 않음\n"
        "3. 배정한 뒤 모든 팀의 인원은 2명 이상 4명 이하임(빈 팀 없음)\n"
        "4. 한 팀 안에 주 역할(main_role)이 같은 학생이 2명 이상이면 안 됨\n"
        "5. 모든 팀에는 '기획자'를 맡을 학생과 '웹 프로그래머'를 맡을 학생이 서로 다른 사람으로 1명씩 있어야 함. "
        "주 역할이나 보조 역할(sub_roles) 가운데 하나가 그 역할이면 맡을 수 있음. 한 학생이 둘 다 맡을 수는 없음\n\n"
        "지금 상태(JSON)\n"
        f"{json.dumps(data, ensure_ascii=False, indent=1)}\n\n"
        "설명 없이 아래 형식의 JSON만 답하세요. team은 팀 번호(정수)입니다.\n"
        '{"assignments": [{"student_no": "학번", "team": 1}]}'
    )


def parse_proposal(text: str) -> list[tuple[str, int]]:
    """모델의 답에서 배정안을 꺼냄. 코드 블록이나 앞뒤 설명이 붙어 있어도 첫 JSON 객체를 읽음."""
    if not text or not text.strip():
        raise ModelFailure("빈 응답")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ModelFailure("응답에 JSON이 없음")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise ModelFailure("JSON 형식이 틀림") from None
    items = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ModelFailure("assignments 목록이 없음")
    proposal = []
    for item in items:
        try:
            team = item["team"]
            team_no = team if isinstance(team, int) else int(re.sub(r"\D", "", str(team)))
            proposal.append((str(item["student_no"]).strip(), team_no))
        except (KeyError, TypeError, ValueError):
            raise ModelFailure("배정 항목의 형식이 틀림") from None
    return proposal


# ---------- 오픈라우터 호출 ----------

def call_openrouter(api_key: str, model: str, prompt: str) -> str:
    """모델 하나를 부르고 답의 본문을 돌려줌. 실패하면 ModelFailure."""
    if not api_key:
        raise ModelFailure("OPENROUTER_API_KEY가 없음")
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "team-formation-app"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_TOKENS,
                "temperature": 0.2,
                # 추론 모델이 생각하는 데 토큰을 다 써서 빈 응답을 내는 일을 줄임(공고 4.3절)
                "reasoning": {"effort": "low"},
            },
            timeout=(10, MODEL_TIMEOUT + 5),
        )
    except requests.RequestException as e:
        raise ModelFailure(f"연결 오류({type(e).__name__})") from None
    if response.status_code != 200:
        raise ModelFailure(f"HTTP {response.status_code}{_error_hint(response)}")
    try:
        body = response.json()
    except ValueError:
        raise ModelFailure("응답이 JSON이 아님") from None
    if body.get("error"):
        raise ModelFailure(f"오류 응답({str(body['error'].get('message', ''))[:80]})")
    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if not content or not str(content).strip():
        raise ModelFailure("빈 응답")
    return str(content)


def _error_hint(response) -> str:
    hints = {429: " 사용량 제한", 401: " 키가 틀림", 402: " 크레딧 없음", 404: " 모델 없음"}
    return hints.get(response.status_code, "")


# ---------- 1차, 2차, 3차 모델과 직접 배정 ----------

Progress = Callable[[int, str, float], None]  # (몇 차, 모델, 경과 초)
Caller = Callable[[str, str, str], str]  # (키, 모델, 프롬프트) -> 답


def run_assignment(
    teams: dict[int, list[Student]],
    unassigned: list[Student],
    api_key: str,
    *,
    models: tuple[str, ...] = MODELS,
    timeout: float = MODEL_TIMEOUT,
    on_progress: Progress | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    caller: Caller = call_openrouter,
) -> AssignResult:
    prompt = build_prompt(teams, unassigned)
    attempts: list[Attempt] = []

    for order, model in enumerate(models, start=1):
        start = time.monotonic()
        future = _executor.submit(caller, api_key, model, prompt)
        outcome = ""
        proposal = None
        while True:
            elapsed = time.monotonic() - start
            if on_progress:
                on_progress(order, model, elapsed)
            try:
                text = future.result(timeout=min(1.0, max(0.05, timeout - elapsed)))
            except FutureTimeout:
                if time.monotonic() - start >= timeout:
                    future.cancel()
                    outcome = f"시간 초과({timeout:.0f}초)"
                    break
                continue
            except ModelFailure as e:
                outcome = str(e)
                break
            except Exception as e:  # 예상하지 못한 오류도 실패로 보고 다음 모델로 넘어감
                outcome = f"오류({type(e).__name__})"
                break
            try:
                proposal = parse_proposal(text)
                problems = rules.validate_assignment(Assignment(teams, unassigned, proposal))
                outcome = "성공" if not problems else "검사 불통과: " + "; ".join(problems[:3])
            except ModelFailure as e:
                outcome = str(e)
            break
        attempt = Attempt(order, model, outcome, round(time.monotonic() - start, 1))
        attempts.append(attempt)
        if on_attempt:
            on_attempt(attempt)
        if outcome == "성공":
            return AssignResult(proposal, f"{order}차 모델({model})", attempts)

    fallback = solver.find_assignment(teams, unassigned)
    if fallback is None:  # 미리 검사했으므로 보통 일어나지 않음
        return AssignResult([], "없음", attempts)
    return AssignResult(fallback, "앱이 직접 배정(3차 모델까지 실패)", attempts)
