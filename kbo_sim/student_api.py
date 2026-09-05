"""
student_api.py
---------------
학생이 제출하는 "출전선수 결정 함수"의 계약(interface)과, 그 함수를 안전하게(강제 타임아웃 포함)
격리 실행하는 러너를 정의한다.

============================================================
학생이 구현해야 하는 함수 시그니처 (정확히 이 이름/인자 순서를 지켜야 함)
============================================================

    def decide_lineup(is_offense, my_team, opponent_team, matchups, context, rng):
        ...
        return lineup  # pCode 정수 리스트 (길이 9 또는 10, 아래 설명 참고)

인자
----
is_offense : bool
    True면 이번 하프이닝에 "공격"입니다 (타순 9명을 정해야 함).
    False면 "수비"입니다 (수비진 10명을 정해야 함).

my_team : pandas.DataFrame
    우리 팀 전체 선수(타자+투수) 데이터. 각 행 = 선수 1명. 실제 KBO 2025시즌 기록 컬럼들
    (AVG, OPS, ERA, WHIP 등) + 이번 경기 진행 중 상태 컬럼이 합쳐져 있습니다:
      - pCode (진짜 키), displayId(표시용, "팀명+등번호+이름"), name, position, role('타자'/'투수')
      - health_pct : 0~100, 현재 체력 (100=쌩쌩, 0=탈진)
      - pitch_count / pitch_target : 투수만 유효 (그 외 NaN)
      - swing_count / swing_target : 타자(수비수 포함)만 유효 (그 외 NaN)
    체력은 절대 회복되지 않고 경기 내내 누적됩니다.

opponent_team : pandas.DataFrame
    상대 팀 전체 선수 데이터. my_team과 동일한 스키마 (상대 팀 선수들의 체력도 전부 포함됩니다).

matchups : pandas.DataFrame
    투수-타자 맞대결 통산 기록 (pitcherPCode, hitterPCode, AVG, PA, H, HR, SO ... 등).
    공격 턴이면 "우리 타자 x 상대 투수", 수비 턴이면 "우리 투수 x 상대 타자(대략, 직전 라인업 기준)"
    조합만 담겨 있습니다. 기록이 없는 조합은 그냥 이 표에 나타나지 않습니다 — 즉 없으면
    개인 스탯 기반으로 시뮬레이션 엔진이 알아서 처리하니, 학생 알고리즘은 이 표에 있는 것만
    참고하면 됩니다.

호출 시점 (중요)
--------------
이 함수는 **이닝이 시작될 때 한 번에 4번** 호출됩니다 — 두 팀 × (수비, 공격).
초/말 공수교대 때는 다시 호출되지 않고, 이닝 시작에 확정된 명단이 그 이닝 내내 쓰입니다.

    N회 시작 → ① 홈팀 수비(초에 사용)  ② 원정팀 수비(말에 사용)
             → ③ 원정팀 공격(초에 사용) ④ 홈팀 공격(말에 사용)
             → N회초 진행 → N회말 진행 → (N+1)회 시작 → ...

수비를 먼저 정하기 때문에, 공격 호출 때는 그 이닝에 상대할 투수/포수가 이미 정해져 있습니다.
다만 **말 공격 라인업도 초가 진행되기 전에 정해집니다.** 즉 말 공격을 결정할 때 보는 점수와
체력은 "그 이닝 시작 시점"의 값이며, 초 공격에서 벌어진 일은 아직 반영되어 있지 않습니다.
(이닝 도중 교체가 없는 것과 같은 이유로, 한 이닝은 통째로 미리 계획하는 방식입니다)

context : dict
    {
      "inning": int,                       # 현재 이닝 (1~9, 연장시 10+)
      "half": "top" | "bottom",             # 이 명단이 사용될 하프이닝
      "my_score": int, "opponent_score": int,
      "outs": 0,                            # 하프이닝 시작 시점이므로 항상 0
      "batting_order_start_index": int,     # 0~8. 이번에 반환할 9명 리스트 중 몇 번 인덱스부터
                                             # 타순이 시작되는지 (공격/수비 모두 제공 — 수비팀은
                                             # "상대의 이번 타순 시작번호"를 참고용으로 받음)
      "my_prev_lineup": [pCode,...] | None,  # 우리 팀이 직전에 제출한 라인업 (없으면 None)
      "opponent_prev_lineup": [pCode,...] | None,  # 상대가 "직전 이닝"에 제출한 라인업
      "opp_pitcher_pcode": int | None,      # 공격 턴에만 제공: 이번 하프 상대 선발/등판 투수
      "opp_catcher_pcode": int | None,      # 공격 턴에만 제공: 이번 하프 상대 포수
      "time_budget_sec": 10.0,              # 이 함수에 주어진 제한시간(초). 초과 시 실격/폴백 처리됨
    }

rng : random.Random
    이 알고리즘 호출 전용 난수 생성기. **반드시 이 rng만 사용하세요.** 전역 random 모듈이나
    random.seed()를 호출해도 이 게임의 시뮬레이션 결과(안타/삼진 등)에는 절대 영향을 주지
    않습니다 (엔진 RNG와 완전히 분리되어 있음). 다만 여러분의 알고리즘 자체가 재현 가능하게
    동작하길 원한다면 이 rng를 사용하는 게 유일한 방법입니다.

반환값
------
- is_offense=True  -> pCode 정수 9개 리스트. **투수 제외**, 타순 순서대로 (DH 포함).
- is_offense=False -> pCode 정수 10개 리스트. 순서 고정:
      [내야수, 내야수, 내야수, 내야수, 외야수, 외야수, 외야수, 포수, DH, 투수]
      (즉 앞의 4개는 내야수, 그다음 3개는 외야수, 8번째 포수, 9번째 DH, 마지막(10번째)이 투수)

규칙/제약
--------
- 투수 슬롯(수비 리스트의 마지막)에는 반드시 my_team에서 position == '투수'인 선수만 가능합니다.
  (요구사항: "투수는 항상 투수임. 외야수를 투수에 배치 불가.")
- 그 외 슬롯(내야수/외야수/포수/DH)은 투수가 아닌 임의의 우리 팀 타자를 넣을 수 있지만,
  슬롯이 요구하는 포지션과 그 선수의 실제 고정 포지션이 다르면 **그 선수가 관여하는 수비
  플레이의 실책 확률이 50% 증가**합니다. DH 슬롯은 수비를 보지 않으므로 포지션 불일치 페널티가
  적용되지 않습니다.
- 같은 사람을 리스트에 두 번 넣을 수 없습니다.
- 이닝 도중 교체는 없습니다 — 이닝 시작 시 그 이닝에 쓸 전체 명단을 제출하는 방식이며,
  이닝 중간이나 공수교대 때 개별 선수를 바꾸는 절차는 존재하지 않습니다.
- 함수는 제한시간(기본 10초) 안에 반환해야 합니다. 초과하거나 예외가 발생하거나 반환값이
  규칙을 위반하면, 직전에 제출했던 유효한 라인업으로 자동 대체되고(폴백), 그마저 없으면
  (예: 1이닝 초) my_team에 나열된 순서상 앞쪽 선수들로 기본 출전 처리됩니다.

권장 사항 (실행시간 관련, 사전 벤치마크 결과 참고)
------------------------------------------------
- population/generation, tabu iteration 등은 pop<=100, gens<=200, tabu iters<=300 수준을
  권장합니다. 이 정도면 대부분의 순수 파이썬 구현이 10초 제한에 여유 있게 들어옵니다.
- 적합도 함수 안에서 매번 DataFrame을 필터링(df[df['team']==x] 등)하지 말고, 함수 시작 시
  한 번 dict/array로 변환해 캐싱해서 쓰세요. (반복 필터링은 수천 번 호출 시 수 초의 오버헤드를
  추가로 만듭니다.)
- 적합도 평가 내부에서 몬테카를로 반복(수십 회 이상)을 도는 습관은 매우 위험합니다 — population과
  결합되면 쉽게 10초를 넘깁니다.
"""
from __future__ import annotations

import importlib.util
import multiprocessing as mp
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from .data_pipeline import LeagueData
from .models import GameRosterState, Team

REQUIRED_FUNC_NAME = "decide_lineup"
DEFAULT_TIMEOUT_SEC = 10.0


class StudentAlgoError(Exception):
    pass


# ---------------------------------------------------------------------------
# 학생 팀 데이터(pd.DataFrame) 구성
# ---------------------------------------------------------------------------

STATUS_COLS_BATTER = ["health_pct", "swing_count", "swing_target"]
STATUS_COLS_PITCHER = ["health_pct", "pitch_count", "pitch_target"]


def team_status_dataframe(league: LeagueData, team: Team, roster_state: GameRosterState) -> pd.DataFrame:
    rows = []
    for pcode in team.batter_pcodes:
        rec = dict(league.batter(pcode))
        rt = roster_state.get(pcode)
        rec["role"] = "타자"
        rec["health_pct"] = rt.health_pct()
        rec["swing_count"] = rt.swing_count
        rec["swing_target"] = rt.swing_target
        rec["pitch_count"] = None
        rec["pitch_target"] = None
        rows.append(rec)
    for pcode in team.pitcher_pcodes:
        rec = dict(league.pitcher(pcode))
        rt = roster_state.get(pcode)
        rec["role"] = "투수"
        rec["health_pct"] = rt.health_pct()
        rec["pitch_count"] = rt.pitch_count
        rec["pitch_target"] = rt.pitch_target
        rec["swing_count"] = None
        rec["swing_target"] = None
        rows.append(rec)
    df = pd.DataFrame(rows)
    # event_rate/event_counts 같은 내부용 dict 컬럼은 학생에게 굳이 노출할 필요 없어 제거
    for c in ("event_rate", "event_counts"):
        if c in df.columns:
            df = df.drop(columns=[c])
    return df


def matchup_dataframe(league: LeagueData, pitcher_pcodes: List[int], hitter_pcodes: List[int]) -> pd.DataFrame:
    p_set, h_set = set(int(p) for p in pitcher_pcodes), set(int(h) for h in hitter_pcodes)
    rows = [row for (p, h), row in league.matchup_index.items() if p in p_set and h in h_set]
    if not rows:
        return pd.DataFrame(columns=["pitcherPCode", "hitterPCode", "AVG", "PA", "AB", "H", "2B", "3B", "HR",
                                      "RBI", "BB", "HBP", "SO", "SLG", "OBP", "OPS"])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 격리 실행 (하드 타임아웃)
# ---------------------------------------------------------------------------

def load_student_module(filepath: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise StudentAlgoError(f"파일을 불러올 수 없습니다: {filepath}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, REQUIRED_FUNC_NAME):
        raise StudentAlgoError(f"'{REQUIRED_FUNC_NAME}' 함수가 정의되어 있지 않습니다: {filepath}")
    return mod


def _worker(filepath, module_name, kwargs, result_queue):
    try:
        mod = load_student_module(filepath, module_name)
        fn = getattr(mod, REQUIRED_FUNC_NAME)
        result = fn(**kwargs)
        result_queue.put(("ok", result))
    except Exception as e:  # noqa: BLE001 - 학생 코드는 무슨 예외를 던질지 알 수 없음
        result_queue.put(("error", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"))


@dataclass
class DecisionOutcome:
    status: str            # 'ok' | 'timeout' | 'error' | 'crash' | 'invalid'
    elapsed: float
    lineup: Optional[List[int]]
    error: Optional[str]


def run_student_decision(filepath: str, module_name: str, *, is_offense: bool, my_team: pd.DataFrame,
                          opponent_team: pd.DataFrame, matchups: pd.DataFrame, context: dict,
                          rng, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> DecisionOutcome:
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context("spawn")
    q = ctx.Queue()
    kwargs = dict(is_offense=is_offense, my_team=my_team, opponent_team=opponent_team,
                  matchups=matchups, context=context, rng=rng)
    p = ctx.Process(target=_worker, args=(filepath, module_name, kwargs, q))
    t0 = time.time()
    p.start()
    p.join(timeout_sec)
    elapsed = time.time() - t0
    if p.is_alive():
        p.terminate()
        p.join(1.0)
        if p.is_alive():
            p.kill()
            p.join()
        return DecisionOutcome("timeout", elapsed, None, f"{timeout_sec:.0f}초 제한시간 초과 (강제 종료됨)")
    if q.empty():
        return DecisionOutcome("crash", elapsed, None, "학생 프로세스가 결과 없이 종료되었습니다 (예외적 크래시)")
    status, payload = q.get()
    if status == "error":
        return DecisionOutcome("error", elapsed, None, payload)
    return DecisionOutcome("ok", elapsed, payload, None)


# ---------------------------------------------------------------------------
# 반환 라인업 검증 + 기본(폴백) 라인업
# ---------------------------------------------------------------------------

def default_offense_lineup(team: Team) -> List[int]:
    return list(team.batter_pcodes[:9])


def default_defense_lineup(team: Team) -> List[int]:
    ifs = team.roster_by_position.get("내야수", [])[:4]
    ofs = team.roster_by_position.get("외야수", [])[:3]
    c = team.roster_by_position.get("포수", [])[:1]
    used = set(ifs) | set(ofs) | set(c)
    dh = next((p for p in team.batter_pcodes if p not in used), None)
    pitcher = team.pitcher_pcodes[0] if team.pitcher_pcodes else None
    lineup = list(ifs) + list(ofs) + list(c) + [dh] + [pitcher]
    return lineup


def validate_lineup(league: LeagueData, team: Team, lineup, is_offense: bool) -> Optional[str]:
    """문제 없으면 None, 문제 있으면 에러 메시지 문자열 반환."""
    if lineup is None:
        return "반환값이 None입니다"
    try:
        lineup = [int(x) for x in lineup]
    except Exception:  # noqa: BLE001 - 학생이 뭘 반환할지 알 수 없음
        # int(x)는 x가 무한대/NaN이면 TypeError/ValueError가 아니라 OverflowError를 던지고,
        # 그 외에도 커스텀 __int__ 구현 등 예측 불가능한 예외가 나올 수 있어 광범위하게 잡는다.
        return "반환값을 정수 pCode 리스트로 변환할 수 없습니다 (무한대/NaN이거나 정수로 변환할 수 없는 값이 있습니다)"

    expected_len = 9 if is_offense else 10
    if len(lineup) != expected_len:
        return f"리스트 길이가 {len(lineup)}입니다 (기대값 {expected_len})"
    if len(set(lineup)) != len(lineup):
        return "리스트에 중복된 선수가 있습니다"

    roster = set(team.batter_pcodes) | set(team.pitcher_pcodes)
    for p in lineup:
        if p not in roster:
            return f"pCode {p}는 우리 팀 선수가 아닙니다"

    if is_offense:
        for p in lineup:
            if p in team.pitcher_pcodes:
                return f"공격 라인업에 투수(pCode {p})가 포함되어 있습니다 (DH 규정 위반)"
    else:
        pitcher_slot = lineup[9]
        if pitcher_slot not in team.pitcher_pcodes:
            return "수비 라인업의 마지막(10번째) 자리는 반드시 실제 투수여야 합니다"
        for p in lineup[:9]:
            if p in team.pitcher_pcodes:
                return "투수는 수비 라인업의 마지막 자리(10번째)에만 위치할 수 있습니다"
    return None
