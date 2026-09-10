"""
example_tabu_lineup.py
-----------------------
Tabu Search 제출물 — **체력(스태미너) 배분**을 1순위로 놓고 라인업을 짠다.

왜 체력이 핵심인가
==================
엔진의 체력 곡선(kbo_sim/fatigue.py)을 그대로 계산해 보면 이렇다.

    야수(목표 스윙 10.5회, 수비 1이닝당 3~5스윙 + 타석당 1.55스윙)
      수비 1이닝 후 : 누적  5.0스윙 → 체력 100%
      수비 2이닝 후 : 누적 10.0스윙 → 체력  68%
      수비 3이닝 후 : 누적 15.0스윙 → 체력   0%   ← 절벽

시그모이드는 목표치 앞에서는 평평하고 목표치에서 수직으로 떨어진다. 그래서
**현재 health_pct를 보고 반응하는 방식은 항상 한 박자 늦는다** — 2이닝째까지
100%로 보이다가 3이닝째에 이미 탈진해 있다. 이 예제의 이전 버전이 체력을
`0.4 + 0.6 * health` 같은 선형 항으로만 쓰던 것이 정확히 그 함정이었다.

그래서 이 버전은 "지금 체력"이 아니라 **"이 배치가 앞으로 깎아먹을 체력"**을 본다.

    (1) 이번 이닝에 그 선수가 소모할 스윙/투구수를 먼저 더한다(선반영).
    (2) 이닝 중간 시점의 능력배수로 이번 이닝 기여를 평가한다.
    (3) 그 소모로 **남은 이닝에서 잃게 될 가치**를 기회비용으로 빼준다.

DH 자리는 수비 소모가 없어서(엔진은 defense[0..7]에만 수비 체력을 물린다)
9이닝을 내리 뛰어도 체력 97%가 남는다. 위 (3) 덕분에 탐색이 알아서
"제일 좋은 타자는 DH에 모셔두고, 수비는 체력을 써도 아까울 게 없는 선수로 돌린다"를
찾아낸다 — DH를 특별취급하는 하드코딩은 한 줄도 없다.

팀 전체로 보면 이건 자원배분 문제다.
    공급 = 야수 27명 × 10.5스윙  ≈ 283스윙
    수요 = 9이닝 × 8수비 × 4.0   ≈ 288스윙  (+ 타석 소모 약 85)
공급이 수요보다 적다. 즉 **아무도 안 지치게 하는 건 불가능**하고, 누구의 체력을
어디에 쓸지 고르는 게 전부다. 그래서 이닝이 늦을수록 기회비용을 0에 수렴시켜
9회에는 체력을 아끼지 않고 전부 태운다.

그 밖의 업그레이드
==================
- 평가 단위를 OPS 가중합 → **기대 득점(선형 가중치)**으로 교체.
- 체력이 확률에 붙는 방식을 엔진과 동일하게 재현:
  유리사건 × (타자배수/투수배수)^0.86, 불리사건은 그 역수 (probability.py).
- 타순 가치는 고정 가중치 배열 대신 **그 타순이 실제로 타석에 설 확률**로 계산.
  (아웃 3개 전에 t번째 타자까지 도달할 확률 — 이닝 시작 인덱스까지 반영)
  이 확률이 곧 타석 스윙 소모량이라, 타순과 체력이 자연스럽게 연동된다.
- 상대 투수의 체력, 맞대결(matchups) 표본을 평가에 반영.
- 투수는 무작위 이웃탐색 대신 **전수 비교로 정확히 최적**을 고른다(후보 수십 명뿐).
  누적 투구수 대비 목표치를 보고 "이번 이닝을 끝까지 버틸 수 있는가"를 적분한다.
- Tabu 기법 자체도 보강: 역이동 금지, 열망 기준, 정체 시 다변화(재시작).

측정 결과와 남은 과제
=====================
이전 버전과 홈/원정을 서로 바꿔가며 붙인 80경기(튜닝에 쓰지 않은 시드)에서
40승 11무 29패(승점비율 0.569), 득점 270 대 217이었다.

수비 출전 시점의 평균 체력을 이닝별로 재보면 성격이 분명히 드러난다.

    이닝    1     2     3     4     5     6     7     8     9   | 전체
    개선  99.7  98.8  96.8  93.9  90.9  69.6  40.3  18.1   6.7 | 69.0
    이전  99.8  82.1  66.2  79.6  79.9  69.8  60.3  43.6  21.8 | 67.9

즉 이건 "팀 전체를 덜 지치게" 만든 게 아니다(전체 평균은 69.0 대 67.9로 사실상 같다).
위에 적었듯 공급(283스윙)이 수요(372스윙)보다 적어서 총량은 줄일 수 없기 때문이다.
바뀐 건 **체력을 언제·누구에게 쓰느냐**다. 초반 5이닝을 거의 100%로 굴리고,
좋은 타자는 DH로 피신시킨다(DH 평균 OPS 0.882 대 수비 8자리 0.627).

남은 과제: 대신 7~9회에 팀이 바닥난다(9회 6.7%). 승부처인 종반을 시체로 치르는 셈이라
여기가 다음 개선 지점이다. 예를 들어 종반용으로 몇 명을 아예 출전시키지 않고 아껴두는
'예약(reserve)' 개념을 넣거나, 이닝별 레버리지(점수차·아웃카운트)를 기회비용에
곱하는 식이 후보다. 단, FUTURE_COST_W를 그냥 키우는 방식은 격자탐색에서 효과가
확인되지 않았다.

이닝 선발 규칙: decide_lineup은 이닝마다 팀당 한 번 호출되며 {"defense": [10명],
"offense": [9명]}을 반환한다. defense는 [내야x4, 외야x3, 포수, DH, 투수] 순서,
offense는 defense의 앞 9명(투수 제외)을 타순대로 재배열한 것이다. 공수교대 때 교체는 없다.
"""
import math
import time

import pandas as pd

# ---------------------------------------------------------------------
# 엔진에서 그대로 옮겨온 상수 (kbo_sim/fatigue.py, probability.py, traits.py)
# 엔진을 import할 수 없으므로 값을 복제한다. 엔진이 바뀌면 여기도 맞춰야 한다.
# ---------------------------------------------------------------------
BAT_STEEPNESS, BAT_MAX_DROP = 16.0, 0.63      # 야수: 가파른 절벽
PIT_STEEPNESS, PIT_MAX_DROP = 6.5, 0.73       # 투수: 완만하지만 더 깊게
FATIGUE_ALPHA = 0.86                           # 체력비 -> 사건확률 배수 지수
BASE_ERROR_RATE = {"포수": 0.010, "내야수": 0.022, "외야수": 0.014, "투수": 0.018}
MISMATCH_ERROR_MULT = 1.5
MEAN_ERROR_MULT = 1.15                         # 개인 실책성향 U(0.5,1.8)의 평균 (엔진 비공개값)

# 엔진을 돌려 실측한 소모 계수
FIELD_SWINGS_PER_INNING = 4.0                  # 수비 1이닝 = 스윙 3~5회의 평균
SWINGS_PER_PA = 1.555                          # 타석 1번당 평균 스윙 수
PITCHES_PER_PA = 3.33                          # 타석 1번당 평균 투구 수
OUT_RATE_PER_PA = 0.66                         # 타석당 아웃 확률(타순 도달 확률 계산용)

# 사건별 득점 가치(아웃 대비). 세이버메트릭스 선형 가중치.
RUN_VALUE = {"BB": 0.63, "HBP": 0.66, "1B": 0.78, "2B": 1.09,
             "3B": 1.40, "HR": 1.72, "SO": -0.02, "OUT": 0.0}
EVENTS = ("BB", "HBP", "1B", "2B", "3B", "HR", "SO", "OUT")
FAVORABLE = ("BB", "HBP", "1B", "2B", "3B", "HR")   # 타자에게 유리 (체력비가 곱해짐)
# 리그 평균 사건 분포(사전분포). 표본이 적은 선수를 이쪽으로 축소시킨다.
PRIOR = {"BB": 0.090, "HBP": 0.015, "1B": 0.170, "2B": 0.045,
         "3B": 0.005, "HR": 0.025, "SO": 0.190, "OUT": 0.460}
PRIOR_PA, PRIOR_TBF = 60.0, 80.0
MATCHUP_SHRINK_PA = 15.0                       # 엔진과 동일

# 수비 기회 배분(타구가 그 자리로 갈 확률)과 실책 1개의 실점 비용
CHANCE_SHARE = (0.12, 0.12, 0.12, 0.12, 0.15, 0.15, 0.15, 0.02)   # 내야4·외야3·포수
BALLS_IN_PLAY_PER_INNING = 2.9
ERROR_RUN_COST = 0.50

SLOT_POS = ["내야수", "내야수", "내야수", "내야수", "외야수", "외야수", "외야수", "포수", "DH", "투수"]
LAST_INNING = 9

# -- 체력 기회비용 가중치 --------------------------------------------
# 이번 이닝에 소모한 체력 때문에 "남은 이닝에서 잃는 가치"에 곱하는 계수.
# 이 값이 0이면 예전 버전처럼 근시안적으로 매 이닝 최고 타자만 갈아넣게 된다.
FUTURE_COST_W = 0.45
# 남은 이닝 중 그 선수를 다시 쓸 법한 비율(전원을 매 이닝 쓸 수는 없으므로 1보다 작다)
REUSE_FRACTION = 0.45
# 남은 이닝 수에 대한 기회비용의 차수. 1.0 = "남은 이닝 수에 비례"(선형).
# 지금 Δ만큼 체력을 태우면 앞으로 쓸 (horizon x REUSE_FRACTION) 이닝 각각에서
# Δ만큼 손해를 보므로 선형이 이론적으로 맞는 형태다.
#
# 주의(튜닝 결과): 40경기 격자탐색에서 FUTURE_COST_W>0은 W=0보다 확실히 좋았지만
# (승점비율 약 0.64 대 0.53), W와 이 차수의 '정확한 값'까지는 구분되지 않았다.
# 셀당 40경기면 표준오차가 ±0.08이라 0.1~0.2 차이는 잡음이다. 그래서 격자의 최고점을
# 그대로 쓰지 않고, 이론적으로 맞는 차수(1.0)와 두 시드집합에서 가장 일관됐던
# 가중치(0.45)를 골랐다. 값을 바꿀 땐 반드시 튜닝에 쓰지 않은 시드로 재검증할 것.
HORIZON_EXPONENT = 1.0

# -- Tabu Search 파라미터 (10초 제한에 여유 있게) --------------------
TS_ITERS_DEFENSE, TS_ITERS_OFFENSE = 140, 90
NEIGHBORS_PER_ITER = 30
TABU_TENURE = 8
STAGNATION_LIMIT = 25          # 이만큼 최고해 갱신이 없으면 흔들어서 다시 탐색
SAFETY_MARGIN_SEC = 2.5        # 제한시간에서 이만큼 남겨두고 비상 탈출


def _num(v, default):
    """v가 없거나(None) 결측(NaN)이면 default, 0.0처럼 유효한 실측값이면 그대로 반환한다.
    `row.get(col) or default`로 쓰면 진짜 0인 값(OPS 0.000, ERA 0.00 등)까지 "없는 값" 취급해
    default로 바꿔버리는 버그가 생긴다 (파이썬에서 0은 falsy이기 때문)."""
    return default if v is None or pd.isna(v) else v


# ---------------------------------------------------------------------
# 1. 체력 — 엔진의 시그모이드를 그대로 재현하고, '앞으로'를 계산한다
# ---------------------------------------------------------------------
def _sigmoid_mult(count, target, steepness, max_drop):
    """엔진 fatigue.performance_multiplier와 동일. 1.0=쌩쌩, (1-max_drop)=탈진."""
    target = target if target > 0 else 1.0
    x = (steepness / target) * (count - target)
    if x > 40:
        sig = 1.0
    elif x < -40:
        sig = 0.0
    else:
        sig = 1.0 / (1.0 + math.exp(-x))
    return 1.0 - max_drop * sig


def bat_mult(prof, extra_swings=0.0):
    """스윙을 extra_swings만큼 '더 했다고 치고' 계산한 능력배수 (선반영이 핵심)."""
    return _sigmoid_mult(prof["swings"] + extra_swings, prof["swing_target"],
                         BAT_STEEPNESS, BAT_MAX_DROP)


def pit_mult(prof, extra_pitches=0.0):
    return _sigmoid_mult(prof["pitches"] + extra_pitches, prof["pitch_target"],
                         PIT_STEEPNESS, PIT_MAX_DROP)


def _target_from_health(health_pct, max_drop, count, steepness):
    """swing_target/pitch_target이 결측일 때 health_pct로부터 목표치를 역산한다.
    health_pct는 배수를 [1-max_drop, 1] -> [0,100]으로 선형 재매핑한 값이라 되돌릴 수 있다."""
    mult = (1.0 - max_drop) + (max(0.0, min(100.0, health_pct)) / 100.0) * max_drop
    ratio = (1.0 - mult) / max_drop
    if ratio <= 1e-9 or ratio >= 1 - 1e-9 or count <= 0:
        return None                      # 정보가 없다 — 호출부에서 기본값을 쓴다
    # mult = 1 - max_drop*sig(k*(count-target)), k = steepness/target 를 target에 대해 푼다
    logit = math.log(ratio / (1.0 - ratio))
    denom = steepness + logit
    return count * steepness / denom if denom > 1e-9 else None


# ---------------------------------------------------------------------
# 2. 기록 -> 사건확률 -> 기대득점
# ---------------------------------------------------------------------
def _event_rates(row, is_pitcher):
    """실측 사건 횟수에 리그 사전분포를 더해(축소추정) 표본이 적은 선수를 안정화한다."""
    n = float(_num(row.get("TBF_eff" if is_pitcher else "PA_eff"),
                   _num(row.get("TBF" if is_pitcher else "PA"), 0.0)))
    h = float(_num(row.get("H"), 0.0))
    d = float(_num(row.get("2B"), 0.0))
    t = float(_num(row.get("3B"), 0.0))
    hr = float(_num(row.get("HR"), 0.0))
    bb = float(_num(row.get("BB"), 0.0))
    hbp = float(_num(row.get("HBP"), 0.0))
    so = float(_num(row.get("SO"), 0.0))
    counts = {"BB": bb, "HBP": hbp, "1B": max(h - d - t - hr, 0.0), "2B": d, "3B": t, "HR": hr,
              "SO": so, "OUT": max(n - h - bb - hbp - so, 0.0)}
    k = PRIOR_TBF if is_pitcher else PRIOR_PA
    vals = {ev: max(counts[ev], 0.0) + k * PRIOR[ev] for ev in EVENTS}
    total = sum(vals.values())
    return {ev: v / total for ev, v in vals.items()}


def _blend_matchup(rate, mrow):
    """맞대결 실적이 있으면 표본 크기에 비례해 섞는다 (엔진과 동일한 축소상수)."""
    if mrow is None:
        return rate
    pa = float(_num(mrow.get("PA"), 0.0))
    if pa <= 0:
        return rate
    h = float(_num(mrow.get("H"), 0.0))
    d = float(_num(mrow.get("2B"), 0.0))
    t = float(_num(mrow.get("3B"), 0.0))
    hr = float(_num(mrow.get("HR"), 0.0))
    bb = float(_num(mrow.get("BB"), 0.0))
    hbp = float(_num(mrow.get("HBP"), 0.0))
    so = float(_num(mrow.get("SO"), 0.0))
    emp = {"BB": bb / pa, "HBP": hbp / pa, "1B": max(h - d - t - hr, 0.0) / pa, "2B": d / pa,
           "3B": t / pa, "HR": hr / pa, "SO": so / pa,
           "OUT": max(pa - h - bb - hbp - so, 0.0) / pa}
    w = pa / (pa + MATCHUP_SHRINK_PA)
    mixed = {ev: w * emp[ev] + (1 - w) * rate[ev] for ev in EVENTS}
    total = sum(mixed.values())
    return {ev: v / total for ev, v in mixed.items()}


def _runs_per_pa(rate, batter_mult, pitcher_mult):
    """체력을 엔진과 똑같은 방식으로 확률에 반영한 뒤 기대 득점가치를 낸다.
    유리사건 × (타자배수/투수배수)^0.86, 불리사건(SO/OUT)은 그 역수, 그리고 재정규화."""
    factor = (batter_mult / max(pitcher_mult, 1e-3)) ** FATIGUE_ALPHA
    inv = 1.0 / max(factor, 1e-3)
    adj = {ev: rate[ev] * (factor if ev in FAVORABLE else inv) for ev in EVENTS}
    total = sum(adj.values())
    return sum(RUN_VALUE[ev] * v / total for ev, v in adj.items())


# ---------------------------------------------------------------------
# 3. 타순별 '타석에 설 확률' — 타격 가치와 체력 소모를 동시에 결정한다
# ---------------------------------------------------------------------
def pa_probability_by_turn():
    """선두타자 기준 t번째 타자가 이번 이닝에 타석에 설 확률.
    = 앞선 t타석에서 아웃이 3개 미만일 확률 (이항분포의 꼬리)."""
    q = OUT_RATE_PER_PA
    probs = []
    for t in range(9):
        p = 0.0
        for k in (0, 1, 2):
            if k > t:
                break
            comb = (1.0, float(t), t * (t - 1) / 2.0)[k]
            p += comb * (q ** k) * ((1 - q) ** (t - k))
        probs.append(min(1.0, p))
    return probs


TURN_PA = pa_probability_by_turn()
EXP_PA_PER_INNING = sum(TURN_PA)


# ---------------------------------------------------------------------
# 4. 프로필 구축 (DataFrame은 딱 한 번만 훑는다)
# ---------------------------------------------------------------------
def build_profiles(my_team: pd.DataFrame):
    bat, pit = {}, {}
    for row in my_team.to_dict("records"):
        pcode = int(row["pCode"])
        health = float(_num(row.get("health_pct"), 100.0))
        if row["role"] == "타자":
            swings = float(_num(row.get("swing_count"), 0.0))
            target = _num(row.get("swing_target"), None)
            if target is None:
                target = _target_from_health(health, BAT_MAX_DROP, swings, BAT_STEEPNESS) or 10.5
            bat[pcode] = {
                "pos": row["position"],
                "rate": _event_rates(row, False),
                "swings": swings,
                "swing_target": float(target),
            }
        else:
            pitches = float(_num(row.get("pitch_count"), 0.0))
            target = _num(row.get("pitch_target"), None)
            if target is None:
                base = float(_num(row.get("NP_per_G"), 20.0)) * 0.70
                target = _target_from_health(health, PIT_MAX_DROP, pitches, PIT_STEEPNESS) or base
            pit[pcode] = {
                "rate": _event_rates(row, True),
                "pitches": pitches,
                "pitch_target": max(float(target), 10.0),
            }
    return bat, pit


def opponent_pitcher_mult(opponent_team: pd.DataFrame, pcode):
    """이번 이닝 상대 투수(직전 이닝 기준)의 예상 체력배수. 모르면 1.0(정상)으로 둔다."""
    if pcode is None or opponent_team is None or opponent_team.empty:
        return 1.0
    rows = opponent_team[opponent_team["pCode"] == pcode]
    if rows.empty:
        return 1.0
    row = rows.iloc[0]
    pitches = float(_num(row.get("pitch_count"), 0.0))
    target = _num(row.get("pitch_target"), None)
    if target is None:
        target = float(_num(row.get("NP_per_G"), 20.0)) * 0.70
    # 이닝 중반까지 더 던진다고 보고 선반영
    half_inning = 0.5 * EXP_PA_PER_INNING * PITCHES_PER_PA
    return _sigmoid_mult(pitches + half_inning, max(float(target), 10.0),
                         PIT_STEEPNESS, PIT_MAX_DROP)


def build_matchup_index(matchups: pd.DataFrame, pitcher_pcode):
    if matchups is None or matchups.empty or pitcher_pcode is None:
        return {}
    if "pitcherPCode" not in matchups.columns:
        return {}
    sub = matchups[matchups["pitcherPCode"] == pitcher_pcode]
    return {int(r["hitterPCode"]): r for r in sub.to_dict("records")}


# ---------------------------------------------------------------------
# 5. 평가함수 — 이번 이닝 기여 - 남은 이닝의 체력 기회비용
# ---------------------------------------------------------------------
class Evaluator:
    """모든 점수는 '기대 득점(런)' 단위다. 높을수록 좋다."""

    def __init__(self, bat, pit, opp_mult, mindex, inning):
        self.bat, self.pit = bat, pit
        self.opp_mult = opp_mult
        self.mindex = mindex
        # 남은 이닝이 많을수록 지금 체력을 태우는 게 비싸다. 9회엔 0 -> 전부 태운다.
        self.horizon = max(0, LAST_INNING - inning)
        # 앞으로 그 선수를 더 쓰게 될 이닝 수의 기댓값 = 기회비용의 크기
        self.future_innings = (self.horizon ** HORIZON_EXPONENT) * REUSE_FRACTION
        # 배치와 무관한 값은 미리 캐싱해 둔다 (수천 번 호출되는 경로)
        self._rate_cache = {}
        self._value_cache = {}
        self._slot_cache = {}

    # -- 타격 -------------------------------------------------------
    def _rate_vs_opp(self, pcode):
        cached = self._rate_cache.get(pcode)
        if cached is None:
            cached = _blend_matchup(self.bat[pcode]["rate"], self.mindex.get(pcode))
            self._rate_cache[pcode] = cached
        return cached

    def _fresh_value(self, pcode):
        """체력이 온전할 때 그 선수의 타석당 득점가치 (기회비용 계산의 기준)."""
        cached = self._value_cache.get(pcode)
        if cached is None:
            cached = _runs_per_pa(self._rate_vs_opp(pcode), 1.0, 1.0)
            self._value_cache[pcode] = cached
        return cached

    def offense_runs(self, pcode, exp_pa, extra_swings):
        """이번 이닝 그 선수의 기대 득점 기여.
        체력은 이닝 중간 시점(소모의 절반이 진행된 시점)으로 평가한다."""
        mult = bat_mult(self.bat[pcode], extra_swings * 0.5)
        return exp_pa * _runs_per_pa(self._rate_vs_opp(pcode), mult, self.opp_mult)

    # -- 수비(실책 실점) --------------------------------------------
    def defense_runs_allowed(self, pcode, slot, extra_swings):
        want = SLOT_POS[slot]
        b = self.bat[pcode]
        mult = bat_mult(b, extra_swings * 0.5)
        p_err = BASE_ERROR_RATE[want] * MEAN_ERROR_MULT
        if b["pos"] != want:
            p_err *= MISMATCH_ERROR_MULT             # 포지션 불일치 = 실책확률 +50%
        p_err *= (1.0 + (1.0 - mult))                # 지칠수록 실책이 는다 (엔진과 동일)
        p_err = max(0.001, min(p_err, 0.35))
        chances = BALLS_IN_PLAY_PER_INNING * CHANCE_SHARE[slot]
        return chances * p_err * ERROR_RUN_COST

    # -- 체력 기회비용 ----------------------------------------------
    def stamina_cost(self, pcode, extra_swings):
        """이번 이닝의 소모 때문에 '남은 이닝'에서 잃게 될 기대 득점.
        절벽 구간에서 Δ배수가 가장 커지므로, 탈진 직전인 선수를 수비에 넣으려 하면
        여기서 큰 페널티가 붙는다 — health_pct를 보고 반응하는 것보다 한 박자 빠르다."""
        if self.future_innings <= 0.0 or extra_swings <= 0.0:
            return 0.0
        b = self.bat[pcode]
        drop = bat_mult(b, 0.0) - bat_mult(b, extra_swings)
        if drop <= 0.0:
            return 0.0
        # 그 선수의 '한 이닝치 타격 가치' × 앞으로 쓸 이닝 수 × 깎인 배수
        per_inning_value = abs(self._fresh_value(pcode)) * EXP_PA_PER_INNING / 9.0
        return FUTURE_COST_W * self.future_innings * drop * per_inning_value

    # -- 슬롯 하나의 순가치 -----------------------------------------
    def slot_value(self, pcode, slot, exp_pa):
        key = (pcode, slot, round(exp_pa, 3))
        cached = self._slot_cache.get(key)
        if cached is not None:
            return cached
        field_swings = 0.0 if SLOT_POS[slot] == "DH" else FIELD_SWINGS_PER_INNING
        total_swings = exp_pa * SWINGS_PER_PA + field_swings
        value = (self.offense_runs(pcode, exp_pa, total_swings)
                 - self.stamina_cost(pcode, total_swings))
        if SLOT_POS[slot] != "DH":
            value -= self.defense_runs_allowed(pcode, slot, total_swings)
        self._slot_cache[key] = value
        return value

    # -- 투수 -------------------------------------------------------
    def pitcher_value(self, pcode):
        """이번 이닝의 실점 억제력을 투구수 누적에 따라 3구간으로 적분한다.
        목표 투구수가 낮은 불펜은 한 이닝을 못 버티고 무너지는 게 그대로 드러난다."""
        p = self.pit[pcode]
        inning_pitches = EXP_PA_PER_INNING * PITCHES_PER_PA
        runs = 0.0
        for frac in (1.0 / 6.0, 0.5, 5.0 / 6.0):       # 이닝의 1/6, 1/2, 5/6 지점
            m = pit_mult(p, inning_pitches * frac)
            runs += _runs_per_pa(p["rate"], 1.0, m) * (EXP_PA_PER_INNING / 3.0)
        value = -runs                                   # 실점은 음수 가치
        # 투수 체력도 남은 이닝의 자산이다 (혹사한 에이스를 계속 올리지 않게)
        if self.future_innings > 0.0:
            drop = pit_mult(p, 0.0) - pit_mult(p, inning_pitches)
            if drop > 0.0:
                strength = abs(_runs_per_pa(p["rate"], 1.0, 1.0)) * EXP_PA_PER_INNING
                value -= FUTURE_COST_W * self.future_innings * drop * strength
        return value


# ---------------------------------------------------------------------
# 6. Tabu Search
# ---------------------------------------------------------------------
def _tabu_search(initial, score_fn, neighbor_fn, iters, rng, deadline):
    """공통 Tabu 탐색기.
    - 이동 속성을 tabu에 기록해 역이동(왔던 자리로 되돌아가기)을 일정 기간 금지
    - 열망 기준: 타부라도 역대 최고해를 넘으면 허용
    - 정체가 길어지면 최고해를 흔들어(perturb) 다른 골짜기로 옮긴다
    """
    cur = list(initial)
    cur_val = score_fn(cur)
    best, best_val = list(cur), cur_val
    tabu = {}
    stagnant = 0

    for it in range(iters):
        if time.perf_counter() > deadline:          # 비상 탈출 (정상 상황에선 걸리지 않는다)
            break
        cand, cand_val, cand_moves = None, float("-inf"), None
        for _ in range(NEIGHBORS_PER_ITER):
            nxt, moves = neighbor_fn(cur, rng)
            if nxt is None:
                continue
            val = score_fn(nxt)
            is_tabu = any(tabu.get(m, -1) > it for m in moves)
            if is_tabu and val <= best_val:          # 열망 기준 미달이면 금지
                continue
            if val > cand_val:
                cand, cand_val, cand_moves = nxt, val, moves
        if cand is None:
            continue
        cur, cur_val = cand, cand_val
        for m in cand_moves:
            tabu[m] = it + TABU_TENURE
        if cand_val > best_val + 1e-12:
            best, best_val = list(cur), cand_val
            stagnant = 0
        else:
            stagnant += 1
            if stagnant >= STAGNATION_LIMIT:         # 다변화: 최고해에서 다시 출발하되 섞는다
                cur = list(best)
                for _ in range(3):
                    i, j = rng.sample(range(len(cur)), 2)
                    cur[i], cur[j] = cur[j], cur[i]
                cur_val = score_fn(cur)
                tabu.clear()
                stagnant = 0
    return best, best_val


def _initial_defense(bat, ev, exp_pa_by_slot):
    """포지션이 맞고 '지금 쓰기 아깝지 않은' 선수부터 채우는 탐욕적 초기해."""
    used = set()
    assign = [None] * 9
    for slot in (8, 7, 0, 1, 2, 3, 4, 5, 6):         # DH·포수를 먼저 확정
        want = SLOT_POS[slot]
        pool = [p for p in bat if p not in used and (want == "DH" or bat[p]["pos"] == want)]
        if not pool:
            pool = [p for p in bat if p not in used]
        if not pool:
            continue
        assign[slot] = max(pool, key=lambda p: ev.slot_value(p, slot, exp_pa_by_slot[slot]))
        used.add(assign[slot])
    return assign


def optimize_defense(bat, ev, rng, deadline):
    """수비 9칸(투수 제외) 배정을 탐색한다.

    타순은 3단계에서 따로 정하고 9명 누구나 어느 타순에도 갈 수 있으므로, 이 단계에서는
    모든 칸에 '평균 기대타석'을 똑같이 준다. 칸마다 다른 기대타석을 주면(예: 타순 가중치를
    슬롯 번호에 그대로 붙이면) DH 칸이 타석이 적은 자리로 잘못 취급돼서, 정작 체력을
    아껴줘야 할 주력 타자를 DH에 앉히지 못하게 된다."""
    exp_pa_by_slot = [EXP_PA_PER_INNING / 9.0] * 9

    def score(assign):
        return sum(ev.slot_value(p, i, exp_pa_by_slot[i]) for i, p in enumerate(assign))

    all_bat = list(bat)

    def neighbor(cur, r):
        if r.random() < 0.5:
            i, j = r.sample(range(9), 2)              # (a) 두 칸 맞바꾸기
            nxt = list(cur)
            nxt[i], nxt[j] = nxt[j], nxt[i]
            return nxt, ((nxt[i], i), (nxt[j], j))
        in_use = set(cur)                             # (b) 벤치 선수로 교체
        pool = [p for p in all_bat if p not in in_use]
        if not pool:
            return None, None
        i = r.randrange(9)
        nxt = list(cur)
        out_player = nxt[i]
        nxt[i] = r.choice(pool)
        return nxt, ((out_player, i),)                # 빠진 선수의 '복귀'를 금지한다

    init = _initial_defense(bat, ev, exp_pa_by_slot)
    if any(p is None for p in init):                  # 후보가 부족한 비정상 상황 방어
        rest = [p for p in all_bat if p not in set(init)]
        init = [p if p is not None else rest.pop() for p in init]
    best, _ = _tabu_search(init, score, neighbor, TS_ITERS_DEFENSE, rng, deadline)
    return best


def optimize_pitcher(pit, ev):
    """후보가 수십 명뿐이라 전수 비교가 무작위 탐색보다 빠르고 정확하다."""
    return max(pit, key=ev.pitcher_value)


def optimize_order(defense9, ev, start_index, rng, deadline):
    """확정된 9명의 타순. 슬롯 i의 기대타석은 선두타자 기준 (i - start_index) % 9 번째다."""
    slot_of_defense = {p: i for i, p in enumerate(defense9)}
    exp_pa = [TURN_PA[(i - start_index) % 9] for i in range(9)]

    def swings_for(pcode, i):
        dslot = slot_of_defense[pcode]
        field = 0.0 if SLOT_POS[dslot] == "DH" else FIELD_SWINGS_PER_INNING
        return exp_pa[i] * SWINGS_PER_PA + field

    def score(order):
        total = 0.0
        for i, p in enumerate(order):
            # 수비 슬롯은 그대로 두고 타순만 바꾸므로, 수비 실점은 어느 타순이든 동일하다
            sw = swings_for(p, i)
            total += ev.offense_runs(p, exp_pa[i], sw) - ev.stamina_cost(p, sw)
        return total

    def neighbor(cur, r):
        i, j = r.sample(range(9), 2)
        nxt = list(cur)
        nxt[i], nxt[j] = nxt[j], nxt[i]
        return nxt, ((nxt[i], i), (nxt[j], j))

    # 초기해: 기대타석이 많은 자리에 '체력 반영 후' 잘 치는 선수를 놓는다
    ranked = sorted(defense9,
                    key=lambda p: ev.offense_runs(p, 1.0, FIELD_SWINGS_PER_INNING),
                    reverse=True)
    init = [None] * 9
    for p, slot in zip(ranked, sorted(range(9), key=lambda i: exp_pa[i], reverse=True)):
        init[slot] = p
    best, _ = _tabu_search(init, score, neighbor, TS_ITERS_OFFENSE, rng, deadline)
    return best


# ---------------------------------------------------------------------
# 7. 제출 함수
# ---------------------------------------------------------------------
def decide_lineup(my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                  matchups: pd.DataFrame, context: dict, rng):
    started = time.perf_counter()
    budget = float(_num(context.get("time_budget_sec"), 10.0))
    deadline = started + max(budget - SAFETY_MARGIN_SEC, 1.0)

    bat, pit = build_profiles(my_team)
    inning = int(_num(context.get("inning"), 1))
    start_index = int(_num(context.get("batting_order_start_index"), 0)) % 9
    opp_pitcher = context.get("opp_pitcher_pcode")

    ev = Evaluator(bat, pit,
                   opponent_pitcher_mult(opponent_team, opp_pitcher),
                   build_matchup_index(matchups, opp_pitcher),
                   inning)

    # 1) 수비 9칸 배정 (체력 기회비용 포함)
    defense9 = optimize_defense(bat, ev, rng, deadline)
    # 2) 투수는 전수 비교로 정확히
    pitcher = optimize_pitcher(pit, ev)
    # 3) 그 9명의 타순
    offense = optimize_order(defense9, ev, start_index, rng, deadline)

    return {"defense": list(defense9) + [pitcher], "offense": offense}
