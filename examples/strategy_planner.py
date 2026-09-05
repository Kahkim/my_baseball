"""
strategy_planner.py
--------------------
"이닝 하나만 보지 말고, 남은 경기 전체를 보고 자원을 배분하자"는 전략.

이 게임의 진짜 어려움은 한 이닝의 라인업을 잘 짜는 것이 아니라 **9이닝치 체력을 어떻게 나눠
쓰느냐**에 있다. 체력은 회복되지 않고, 야수는 수비 1이닝당 스윙 3~5개를 소모하며 목표치가
20 안팎이다. 즉 한 선수는 대략 4이닝 정도밖에 온전히 뛰지 못한다.

    필요한 수비 슬롯: 9이닝 × 8자리 = 72 슬롯-이닝
    선수 1명이 감당 가능: 약 4이닝
    => 최소 18명 이상을 돌려 써야 한다 (주전 9명 고정으로는 절대 불가능)

그래서 이 구현은 매 이닝 "지금 제일 좋은 선수"가 아니라 **남은 이닝 수를 보고 부하를 분산**한다:

1. 실력이 비슷한(상위권 내) 선수들 중에서는 **가장 덜 지친 선수**를 쓴다 (부하 평준화)
2. 남은 이닝이 적을수록 아끼지 않고 좋은 선수를 몰아 쓴다 (막판에는 체력을 남길 이유가 없다)
3. 투수는 '남은 투구 여력'이 한 이닝(약 18구)을 감당하는 투수 중에서 고르고,
   좋은 투수는 뒤쪽 이닝을 위해 아껴 둔다

학생들에게: 이 구현은 여전히 규칙 기반이다. 여기에 메타휴리스틱을 얹어 **9이닝 전체의 기용
계획**을 탐색하면 더 잘할 수 있다 (조합이 폭발적이라 그리디로는 못 푸는 영역).
"""
import random

import pandas as pd

LEAGUE_OPS, LEAGUE_ERA = 0.750, 4.80
SHRINK_PA, SHRINK_IP = 80.0, 30.0
QUALIFY_PA = 40
TOTAL_INNINGS = 9
FIELD_COST_PER_INNING = 4.0        # 수비 1이닝당 스윙 환산 소모 (엔진: 3~5)
PITCHES_PER_INNING = 18.0          # 한 이닝을 맡기려면 이 정도 여력은 있어야 한다


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


def decide_lineup(is_offense: bool, my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                   matchups: pd.DataFrame, context: dict, rng: random.Random):
    inning = int(context.get("inning", 1) or 1)
    remaining = max(TOTAL_INNINGS - inning + 1, 1)
    # 남은 이닝이 많을수록 체력을 아끼고(=부하 분산), 적을수록 실력 위주로 몰아 쓴다
    conserve = min(remaining / TOTAL_INNINGS, 1.0)

    bat, pit = {}, {}
    for r in my_team.to_dict("records"):
        health = (r.get("health_pct") if r.get("health_pct") is not None else 100) / 100.0
        if r["role"] == "타자":
            pa = float(r.get("PA", 0) or 0)
            swings = float(r.get("swing_count") or 0)
            target = float(r.get("swing_target") or 20.0)
            bat[r["pCode"]] = {
                "pos": r["position"], "health": health, "pa": pa,
                "ops": _shrunk(r, "OPS", LEAGUE_OPS, "PA", SHRINK_PA),
                "obp": _shrunk(r, "OBP", 0.350, "PA", SHRINK_PA),
                "slg": _shrunk(r, "SLG", 0.400, "PA", SHRINK_PA),
                # 앞으로 몇 이닝이나 더 수비를 볼 수 있는지 (음수면 이미 초과)
                "capacity": max(target - swings, 0.0) / FIELD_COST_PER_INNING,
            }
        else:
            ip = float(r.get("IP_f", 0) or 0)
            thrown = float(r.get("pitch_count") or 0)
            ptarget = float(r.get("pitch_target") or 60.0)
            pit[r["pCode"]] = {
                "health": health,
                "era": _shrunk(r, "ERA", LEAGUE_ERA, "IP_f", SHRINK_IP),
                "left": max(ptarget - thrown, 0.0),          # 남은 투구 여력
                "innings_left": max(ptarget - thrown, 0.0) / PITCHES_PER_INNING,
                "trust": ip / (ip + SHRINK_IP),
            }

    def quality(p):
        b = bat[p]
        base = b["ops"] if b["pa"] >= QUALIFY_PA else b["ops"] * 0.72
        return base

    def usable(p):
        """이번 이닝에 실제로 쓸 만한가 = 실력 × 지금 체력 × (남은 여력을 아낄지 여부)"""
        b = bat[p]
        fresh_bonus = min(b["capacity"] / max(remaining, 1), 1.0)   # 남은 이닝을 버틸 수 있는가
        return quality(p) * (0.25 + 0.75 * b["health"]) * (1.0 - conserve * 0.35 * (1 - fresh_bonus))

    if is_offense:
        # 공격은 아낄 이유가 적다(타석 스윙 소모는 수비보다 작음) — 실력·체력 위주
        order = sorted(bat, key=lambda p: quality(p) * (0.3 + 0.7 * bat[p]["health"]),
                       reverse=True)[:9]
        heart = sorted(order, key=lambda p: bat[p]["slg"], reverse=True)[:3]
        rest = sorted([p for p in order if p not in set(heart)],
                      key=lambda p: bat[p]["obp"], reverse=True)
        out = [None] * 9
        out[2], out[3], out[4] = heart
        for i, p in zip([i for i in range(9) if out[i] is None], rest):
            out[i] = p
        return out

    used = set()

    def pick(pos, n):
        pool = [p for p in bat if p not in used and bat[p]["pos"] == pos]
        if len(pool) < n:
            pool += [p for p in bat if p not in used and p not in pool]
        # 실력 상위권을 먼저 추린 뒤, 그 안에서 '가장 덜 지친' 선수를 고른다 = 부하 평준화
        pool.sort(key=usable, reverse=True)
        shortlist = pool[:max(n * 2, n + 3)]
        shortlist.sort(key=lambda p: (bat[p]["capacity"], usable(p)), reverse=True)
        chosen = shortlist[:n]
        used.update(chosen)
        return chosen

    ifs, ofs, cs = pick("내야수", 4), pick("외야수", 3), pick("포수", 1)
    dh = sorted([p for p in bat if p not in used],
                key=lambda p: quality(p) * (0.3 + 0.7 * bat[p]["health"]), reverse=True)[:1]

    # 투수: 한 이닝을 감당할 여력이 있는 투수 중에서 고른다.
    # 남은 이닝이 많으면 좋은 투수를 아끼고(여력 큰 순), 막판이면 실력 순으로 몰아 쓴다.
    def pscore(p):
        v = pit[p]
        if v["innings_left"] < 0.9:          # 이번 이닝을 버티지 못할 투수는 사실상 제외
            return -1.0
        strength = (1.0 / (v["era"] + 1.0)) * (0.4 + 0.6 * v["trust"])
        stock = min(v["innings_left"] / max(remaining, 1), 1.0)
        return strength * (0.35 + 0.65 * v["health"]) * (0.5 + 0.5 * stock)

    ranked = sorted(pit, key=pscore, reverse=True)
    ace = ranked[0]
    if pscore(ace) < 0:                       # 전원 지쳤으면 그나마 여력이 가장 큰 투수
        ace = max(pit, key=lambda p: pit[p]["left"])
    return ifs + ofs + cs + dh + [ace]
