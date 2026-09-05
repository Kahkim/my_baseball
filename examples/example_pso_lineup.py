"""
example_pso_lineup.py
----------------------
PSO(입자 군집 최적화) 예제 제출물.

PSO는 원래 연속공간 알고리즘이라 "선수 배정" 같은 조합 문제에 그대로 쓸 수 없다.
그래서 이 예제는 수업에서 자주 쓰는 **연속 인코딩 → 디코딩** 패턴을 쓴다:

  입자의 위치 x = 선수 평가에 쓸 가중치 벡터 (연속값)
      x = [w_출루, w_장타, w_체력, w_포지션적합, w_스태미너, w_표본신뢰]
  디코딩 d(x)  = 그 가중치로 모든 선수 점수를 매기고 → 규칙에 맞게 그리디로 라인업 구성
  적합도 f(x)  = 그렇게 만들어진 라인업의 기대 성능 점수

즉 PSO는 "누구를 넣을까"가 아니라 **"무엇을 얼마나 중요하게 볼까"** 를 탐색한다.
가중치 공간은 연속이라 PSO가 자연스럽게 작동하고, 디코딩이 제약(포지션·중복·투수)을 항상
만족시키므로 위반해가 나올 수 없다.

  v ← w·v + c1·r1·(pbest − x) + c2·r2·(gbest − x)
  x ← x + v

파라미터는 10초 제한에 여유 있게 들어오도록 작게 잡았다 (입자 18 × 세대 22).

이닝 선발 규칙: 수비 호출에서 투수 포함 10명을 선발합니다. 공격 호출의 my_team은 그 10명만
포함하므로, 투수 제외 9명의 타순만 정하세요. context["selected_lineup"]은 수비 자리 순서의
선발 10명입니다. 공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다.
"""
import random

import pandas as pd

N_PARTICLES = 18
N_ITERS = 22
W_INERTIA, C1, C2 = 0.72, 1.5, 1.5
DIM = 6
X_LO, X_HI = 0.0, 2.0
V_MAX = 0.6

LEAGUE_OPS, LEAGUE_OBP, LEAGUE_SLG, LEAGUE_ERA = 0.750, 0.350, 0.400, 4.80
SHRINK_PA, SHRINK_IP = 80.0, 30.0
SLOT_POS = ["내야수", "내야수", "내야수", "내야수", "외야수", "외야수", "외야수", "포수", "DH", "투수"]
SLOT_OBP_W = [1.6, 1.5, 1.1, 1.0, 1.0, 0.9, 0.8, 0.8, 0.7]
SLOT_SLG_W = [0.8, 0.9, 1.3, 1.5, 1.4, 1.1, 1.0, 0.9, 0.8]


def _num(v, default):
    """v가 없거나(None) 결측(NaN)이면 default, 0.0처럼 유효한 실측값이면 그대로 반환한다.
    `row.get(col) or default`로 쓰면 진짜 0인 값(OPS 0.000, ERA 0.00 등)까지 "없는 값" 취급해
    default로 바꿔버리는 버그가 생긴다 (파이썬에서 0은 falsy이기 때문)."""
    return default if pd.isna(v) else v


def _shrunk(row, col, avg, denom_col, k):
    n = float(_num(row.get(denom_col), 0.0))
    v = float(_num(row.get(col), avg))
    w = n / (n + k)
    return w * v + (1 - w) * avg


def build_profiles(my_team: pd.DataFrame):
    bat, pit = {}, {}
    for row in my_team.to_dict("records"):
        health = (row.get("health_pct") if row.get("health_pct") is not None else 100) / 100.0
        if row["role"] == "타자":
            pa = float(row.get("PA", 0) or 0)
            bat[row["pCode"]] = {
                "pos": row["position"], "health": health, "pa": pa,
                "obp": _shrunk(row, "OBP", LEAGUE_OBP, "PA", SHRINK_PA),
                "slg": _shrunk(row, "SLG", LEAGUE_SLG, "PA", SHRINK_PA),
                "ops": _shrunk(row, "OPS", LEAGUE_OPS, "PA", SHRINK_PA),
                "trust": pa / (pa + SHRINK_PA),      # 표본 신뢰도 0~1
            }
        else:
            ip = float(row.get("IP_f", 0) or 0)
            pit[row["pCode"]] = {
                "health": health, "ip": ip,
                "era": _shrunk(row, "ERA", LEAGUE_ERA, "IP_f", SHRINK_IP),
                "stamina": min(float(_num(row.get("NP_per_G"), 20.0)) / 45.0, 1.0),
                "trust": ip / (ip + SHRINK_IP),
            }
    return bat, pit


def batter_score(b, x, want_pos):
    """가중치 벡터 x로 타자 한 명을 점수화. want_pos가 주어지면 포지션 적합도까지 반영."""
    s = x[0] * b["obp"] + x[1] * b["slg"] + x[2] * (b["health"] - 0.5) + x[5] * (b["trust"] - 0.5) * 0.5
    if want_pos and want_pos not in ("DH",) and b["pos"] != want_pos:
        s -= x[3] * 0.35        # 포지션 불일치 페널티 (실책 확률 +50%)
    return s


def pitcher_score(p, x):
    return (1.0 / (p["era"] + 1.0)) * (0.3 + 0.7 * (x[4] / 2.0 * p["stamina"] + (1 - x[4] / 2.0))) \
        * (0.15 + 0.85 * p["health"]) * (0.4 + 0.6 * p["trust"])


def decode_defense(x, bat, pit):
    """가중치 → 규칙을 만족하는 수비 라인업 (중복 없음, 투수 칸은 진짜 투수)."""
    used, assign = set(), [None] * 10
    for slot, want in enumerate(SLOT_POS):
        if want == "투수":
            continue
        pool = [p for p in bat if p not in used]
        if want != "DH":
            fit = [p for p in pool if bat[p]["pos"] == want]
            pool = fit or pool
        pick = max(pool, key=lambda p: batter_score(bat[p], x, want))
        assign[slot] = pick
        used.add(pick)
    assign[9] = max(pit, key=lambda p: pitcher_score(pit[p], x))
    return assign


def decode_offense(x, bat, start_index):
    """가중치 → 9명 타순. 점수 상위 9명을 뽑아 출루형은 앞, 장타형은 중심타선에 배치."""
    ranked = sorted(bat, key=lambda p: batter_score(bat[p], x, None), reverse=True)[:9]
    # 중심타선(3~5번)에는 장타 비중이 큰 선수, 1~2번에는 출루 비중이 큰 선수
    by_power = sorted(ranked, key=lambda p: bat[p]["slg"], reverse=True)
    heart = by_power[:3]
    rest = [p for p in ranked if p not in set(heart)]
    by_obp = sorted(rest, key=lambda p: bat[p]["obp"], reverse=True)
    order = [None] * 9
    order[2], order[3], order[4] = heart[0], heart[1], heart[2]
    fill = [i for i in range(9) if order[i] is None]
    for i, p in zip(fill, by_obp):
        order[i] = p
    return order


def evaluate(x, bat, pit, is_offense, start_index):
    if is_offense:
        order = decode_offense(x, bat, start_index)
        s = 0.0
        for i, p in enumerate(order):
            b = bat[p]
            s += (b["obp"] * SLOT_OBP_W[i] + b["slg"] * SLOT_SLG_W[i]) * (0.6 + 0.4 * b["health"])
        return s
    assign = decode_defense(x, bat, pit)
    s = 0.0
    for slot, pcode in enumerate(assign):
        want = SLOT_POS[slot]
        if want == "투수":
            p = pit[pcode]
            s += 6.0 * (1.0 / (p["era"] + 1.0)) * (0.3 + 0.7 * p["stamina"]) \
                * (0.15 + 0.85 * p["health"]) * (0.4 + 0.6 * p["trust"])
            continue
        b = bat[pcode]
        s += b["ops"] * (0.4 + 0.6 * b["health"])
        if want != "DH":
            if b["pos"] != want:
                s -= 0.55
            s += 0.35 * b["health"]
    return s


def pso(bat, pit, is_offense, start_index, rng: random.Random):
    pos = [[rng.uniform(X_LO, X_HI) for _ in range(DIM)] for _ in range(N_PARTICLES)]
    vel = [[rng.uniform(-V_MAX, V_MAX) for _ in range(DIM)] for _ in range(N_PARTICLES)]
    pbest = [list(p) for p in pos]
    pbest_val = [evaluate(p, bat, pit, is_offense, start_index) for p in pos]
    g = max(range(N_PARTICLES), key=lambda i: pbest_val[i])
    gbest, gbest_val = list(pbest[g]), pbest_val[g]

    for _ in range(N_ITERS):
        for i in range(N_PARTICLES):
            for d in range(DIM):
                r1, r2 = rng.random(), rng.random()
                v = (W_INERTIA * vel[i][d]
                     + C1 * r1 * (pbest[i][d] - pos[i][d])
                     + C2 * r2 * (gbest[d] - pos[i][d]))
                vel[i][d] = max(-V_MAX, min(V_MAX, v))
                pos[i][d] = max(X_LO, min(X_HI, pos[i][d] + vel[i][d]))
            val = evaluate(pos[i], bat, pit, is_offense, start_index)
            if val > pbest_val[i]:
                pbest[i], pbest_val[i] = list(pos[i]), val
                if val > gbest_val:
                    gbest, gbest_val = list(pos[i]), val
    return gbest


def decide_lineup(is_offense: bool, my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                   matchups: pd.DataFrame, context: dict, rng: random.Random):
    bat, pit = build_profiles(my_team)
    start_index = context.get("batting_order_start_index", 0)
    best_x = pso(bat, pit, is_offense, start_index, rng)
    return decode_offense(best_x, bat, start_index) if is_offense \
        else decode_defense(best_x, bat, pit)
