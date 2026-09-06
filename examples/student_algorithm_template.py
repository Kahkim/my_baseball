"""
student_algorithm_template.py
------------------------------
"나의 구단주가 되어라" 과제 제출 템플릿.

이 파일을 복사해서 본인 학번_이름.py 로 저장한 뒤, decide_lineup() 함수 안을
Tabu Search / PSO / GA 중 하나(또는 조합)로 구현하세요.

===============================================================
지켜야 하는 것
===============================================================
1. 함수 이름/인자 순서를 절대 바꾸지 마세요:
   decide_lineup(my_team, opponent_team, matchups, context, rng)
2. 난수는 반드시 인자로 받은 rng(random.Random 인스턴스)만 사용하세요.
   전역 random 모듈이나 random.seed()를 쓰면 여러분 알고리즘 내부의 재현성에는
   문제가 없지만, 시뮬레이션 엔진 결과에는 어차피 영향을 주지 못합니다 (완전히
   분리된 RNG). 대신 채점/디버깅 시 여러분 알고리즘의 동작을 재현하려면 이 rng를
   써야 합니다.
3. 반환값은 {"defense": [10명], "offense": [9명]} 형태의 dict입니다.
   pCode(정수) 리스트를 쓰면 되고, my_team["pCode"] 컬럼 값을 그대로 쓰면 됩니다.
   - defense: 10명, 순서 고정 [내야수x4, 외야수x3, 포수, DH, 투수] (마지막이 투수)
   - offense: 9명, 투수 제외, 타순 순서. defense의 앞 9명을 재배열한 것이어야 합니다.
4. 이 함수는 이닝마다 팀당 한 번 호출됩니다 (한 번에 공수 명단을 모두 정함).
   제한시간(기본 10초)을 넘기면 직전 이닝 명단으로 자동 대체합니다. 프로세스 시작·import
   비용을 포함하므로 실제 환경에서 반복 수를 조정하세요.
5. 적합도 함수 안에서 매번 DataFrame을 필터링하지 말고, 함수 시작 시 딕셔너리로
   한 번 캐싱해서 쓰세요 (아래 예시 참고).
6. my_team의 AVG/OPS/ERA는 원본 값 그대로라 표본이 적은 선수는 왜곡되어 보입니다
   (예: 1타수 1안타 → OPS 4.000). PA_eff/TBF_eff로 표본크기를 확인해서 리그 평균 쪽으로
   당겨 쓰세요 (아래 batter_score/pitcher_score 예시 참고).

자세한 인자/반환값 스펙은 kbo_sim/student_api.py 모듈 docstring에 전부 설명되어 있습니다.

이닝 선발 규칙: 이닝마다 팀당 한 번 호출되어 그 이닝의 공격 타순과 수비 배치를 함께 정합니다.
공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다. context의
opp_pitcher_pcode/opp_catcher_pcode는 상대의 '직전 이닝' 수비 기준이며 1회엔 None입니다.
"""
import random

import pandas as pd

# ------------------------------------------------------------------------
# 표본이 적은 선수 함정 주의: 예를 들어 1타수 1안타면 원본 AVG=1.000, OPS=4.000으로 보입니다.
# 시뮬레이션 엔진은 내부적으로 표본크기(PA/TBF)에 비례해 리그 평균 쪽으로 당겨서(shrinkage)
# 실제 확률을 계산하므로 그런 선수가 실제로 4할 타자처럼 행동하지는 않습니다 — 하지만 my_team에
# 노출되는 AVG/OPS/ERA 컬럼은 원본 그대로(축소 적용 전)입니다. 아래 batter_score/pitcher_score는
# PA_eff/TBF_eff(엔진이 계산한 유효 표본수)를 이용해 여러분 스코어링에도 같은 보정을 적용하는
# 예시입니다. 이 보정이 없으면 "1타수 1안타" 선수를 4할 타자로 착각해 주전으로 기용하는 실수를
# 하게 됩니다. 자세한 설명은 프로그램_매뉴얼.md 참고.
# ------------------------------------------------------------------------
LEAGUE_AVG_OPS = 0.750
LEAGUE_AVG_ERA = 4.80
BATTER_SHRINK_PA = 30.0    # 이 값이 클수록 표본이 적은 선수를 더 강하게 리그평균으로 당김
PITCHER_SHRINK_TBF = 40.0


def _num(v, default):
    """v가 없거나(None) 결측(NaN)이면 default, 0.0처럼 유효한 실측값이면 그대로 반환한다.
    `row.get(col) or default` 식으로 쓰면 진짜 0인 값(OPS 0.000, ERA 0.00, health_pct 0 등)까지
    "없는 값" 취급해 default로 바꿔버리는 버그가 생긴다 (파이썬에서 0은 falsy이기 때문)."""
    return default if pd.isna(v) else v


def decide_lineup(my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                   matchups: pd.DataFrame, context: dict, rng: random.Random):
    # ------------------------------------------------------------------
    # 0) 자주 쓰는 형태로 미리 캐싱 (매 적합도 평가마다 DataFrame 필터링 금지!)
    # ------------------------------------------------------------------
    batters = my_team[my_team["role"] == "타자"]
    pitchers = my_team[my_team["role"] == "투수"]
    batter_stat = {row["pCode"]: row for _, row in batters.iterrows()}       # pCode -> Series
    pitcher_stat = {row["pCode"]: row for _, row in pitchers.iterrows()}
    matchup_lookup = {(row["pitcherPCode"], row["hitterPCode"]): row for _, row in matchups.iterrows()}

    ifs = batters[batters["position"] == "내야수"]["pCode"].tolist()
    ofs = batters[batters["position"] == "외야수"]["pCode"].tolist()
    cs = batters[batters["position"] == "포수"]["pCode"].tolist()
    all_batter_codes = batters["pCode"].tolist()
    all_pitcher_codes = pitchers["pCode"].tolist()

    # ------------------------------------------------------------------
    # 1) 간단한 적합도(fitness) 함수 예시 - OPS와 체력을 이용한 아주 단순한 점수.
    #    실제 과제에서는 이 부분을 여러분의 메타휴리스틱 탐색으로 대체하세요.
    # ------------------------------------------------------------------
    def batter_score(pcode):
        row = batter_stat[pcode]
        raw_ops = _num(row.get("OPS"), LEAGUE_AVG_OPS)
        pa = _num(row.get("PA_eff", row.get("PA")), 0.0)
        w = pa / (pa + BATTER_SHRINK_PA)               # 표본이 적을수록 w가 0에 가까워짐
        ops = w * raw_ops + (1 - w) * LEAGUE_AVG_OPS    # 리그 평균 쪽으로 축소(shrinkage)
        health = _num(row.get("health_pct"), 100.0) / 100.0
        return ops * (0.5 + 0.5 * health)  # 체력이 떨어지면 점수 하락

    def pitcher_score(pcode):
        row = pitcher_stat[pcode]
        raw_era = _num(row.get("ERA"), LEAGUE_AVG_ERA)
        tbf = _num(row.get("TBF_eff", row.get("TBF")), 0.0)
        w = tbf / (tbf + PITCHER_SHRINK_TBF)
        era = w * raw_era + (1 - w) * LEAGUE_AVG_ERA
        health = _num(row.get("health_pct"), 100.0) / 100.0
        return (1.0 / (era + 1.0)) * (0.5 + 0.5 * health)

    # ------------------------------------------------------------------
    # 2) TODO: 여기를 Tabu Search / PSO / GA로 교체하세요.
    #    아래는 "점수 높은 순으로 그리디하게 채우는" 매우 단순한 자리표시자(placeholder)입니다.
    # ------------------------------------------------------------------
    # (a) 수비: 포지션별 상위 점수 선수 + 나머지 중 1명 DH + 최고점 투수
    chosen_if = sorted(ifs, key=batter_score, reverse=True)[:4]
    chosen_of = sorted(ofs, key=batter_score, reverse=True)[:3]
    chosen_c = sorted(cs, key=batter_score, reverse=True)[:1]
    used = set(chosen_if) | set(chosen_of) | set(chosen_c)
    remaining = [p for p in all_batter_codes if p not in used]
    dh = sorted(remaining, key=batter_score, reverse=True)[0] if remaining else all_batter_codes[0]
    pitcher = sorted(all_pitcher_codes, key=pitcher_score, reverse=True)[0]
    defense = chosen_if + chosen_of + chosen_c + [dh, pitcher]

    # (b) 공격: 선발 9명(투수 제외)을 점수 순으로 세운다 (예시일 뿐 - 타순 최적화 로직으로 대체)
    offense = sorted(defense[:9], key=batter_score, reverse=True)

    return {"defense": defense, "offense": offense}
