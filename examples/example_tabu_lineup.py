"""
example_tabu_lineup.py
-----------------------
Tabu Search 예제 제출물.

GA 예제(example_ga_lineup.py)가 "공격 타순"에 집중한다면, 이 예제는 **수비 배치**를 주력으로
최적화한다. 수비 라인업은 제약이 강한 배정(assignment) 문제라 Tabu Search가 잘 어울린다:

- 해(solution)  = 10칸(내야4·외야3·포수·DH·투수)에 선수를 배정한 것
- 이웃(neighbor) = 두 칸의 선수를 맞바꾸기(swap), 또는 한 칸을 벤치 선수로 교체
- 타부 리스트   = 최근에 건드린 (선수, 칸) 쌍을 일정 기간 금지 → 같은 자리를 왔다갔다 하는 것 방지
- 열망 기준     = 타부라도 지금까지의 최고해보다 좋으면 허용

평가함수는 이 게임의 규칙을 그대로 반영한다:
  ① 포지션 불일치는 실책 확률을 50% 올린다 → 큰 감점
  ② 체력이 떨어진 선수는 수비도 공격도 나빠진다 → 체력 가중
  ③ 투수는 방어율뿐 아니라 '등판당 평균 투구수(스태미너)'가 중요하다
  ④ 타격 생산성이 높은 선수를 필드에 올려야 다음 공격에서 이득

공격 타순도 같은 Tabu Search 틀로 짧게 한 번 더 돌린다.

이닝 선발 규칙: 수비 호출에서 투수 포함 10명을 선발합니다. 공격 호출의 my_team은 그 10명만
포함하므로, 투수 제외 9명의 타순만 정하세요. context["selected_lineup"]은 수비 자리 순서의
선발 10명입니다. 공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다.
"""
import random

import pandas as pd

# --- Tabu Search 파라미터 (10초 제한에 여유 있게 들어오도록 보수적으로 설정) ---
TS_ITERS_DEFENSE = 160
TS_ITERS_OFFENSE = 120
TABU_TENURE = 8
NEIGHBORS_PER_ITER = 24

LEAGUE_OPS, LEAGUE_ERA = 0.750, 4.80
SHRINK_PA, SHRINK_IP = 80.0, 30.0
QUALIFY_PA = 40

# 수비 10칸이 요구하는 포지션 (엔진 규칙과 동일)
SLOT_POS = ["내야수", "내야수", "내야수", "내야수", "외야수", "외야수", "외야수", "포수", "DH", "투수"]


def _num(v, default):
    """v가 없거나(None) 결측(NaN)이면 default, 0.0처럼 유효한 실측값이면 그대로 반환한다.
    `row.get(col) or default`로 쓰면 진짜 0인 값(OPS 0.000, ERA 0.00 등)까지 "없는 값" 취급해
    default로 바꿔버리는 버그가 생긴다 (파이썬에서 0은 falsy이기 때문)."""
    return default if pd.isna(v) else v


def _shrunk(row, col, league_avg, denom_col, k):
    n = float(_num(row.get(denom_col), 0.0))
    v = float(_num(row.get(col), league_avg))
    w = n / (n + k)
    return w * v + (1 - w) * league_avg


def build_profiles(my_team: pd.DataFrame):
    """DataFrame을 매 평가마다 필터링하면 느리다. 딱 한 번 dict로 만들어 두고 쓴다."""
    bat, pit = {}, {}
    for row in my_team.to_dict("records"):
        health = (row.get("health_pct") if row.get("health_pct") is not None else 100) / 100.0
        if row["role"] == "타자":
            bat[row["pCode"]] = {
                "pos": row["position"],
                "ops": _shrunk(row, "OPS", LEAGUE_OPS, "PA", SHRINK_PA),
                "obp": _shrunk(row, "OBP", 0.350, "PA", SHRINK_PA),
                "slg": _shrunk(row, "SLG", 0.400, "PA", SHRINK_PA),
                "pa": float(row.get("PA", 0) or 0),
                "health": health,
            }
        else:
            pit[row["pCode"]] = {
                "era": _shrunk(row, "ERA", LEAGUE_ERA, "IP_f", SHRINK_IP),
                "stamina": float(_num(row.get("NP_per_G"), 20.0)),
                "ip": float(row.get("IP_f", 0) or 0),
                "health": health,
            }
    return bat, pit


# ---------------------------------------------------------------- 수비 평가
def defense_fitness(assign, bat, pit):
    """높을수록 좋은 점수. 포지션 불일치 · 체력 · 타격생산성 · 투수 스태미너를 함께 본다."""
    score = 0.0
    for slot, pcode in enumerate(assign):
        want = SLOT_POS[slot]
        if want == "투수":
            p = pit[pcode]
            quality = 1.0 / (p["era"] + 1.0)               # 방어율이 낮을수록 큼
            stamina = min(p["stamina"] / 45.0, 1.0)         # 한 이닝을 감당할 수 있는가
            score += 6.0 * quality * (0.30 + 0.70 * stamina) * (0.15 + 0.85 * p["health"])
            continue
        b = bat[pcode]
        # 타격 기여 (DH 포함 — 어차피 다음 공격에서 타석에 선다)
        score += b["ops"] * (0.4 + 0.6 * b["health"])
        if want == "DH":
            continue
        # 수비 기여: 포지션이 맞아야 하고 체력이 있어야 한다
        if b["pos"] != want:
            score -= 0.55            # 실책 확률 +50% 페널티를 점수로 환산
        score += 0.35 * b["health"]
    return score


def _legal_defense(bat, pit, rng):
    """규칙을 만족하는 초기해 하나를 만든다 (포지션이 맞는 선수 우선)."""
    used = set()
    assign = [None] * 10
    for slot, want in enumerate(SLOT_POS):
        if want == "투수":
            continue
        pool = [p for p, v in bat.items() if p not in used and v["pos"] == want] if want != "DH" \
            else [p for p in bat if p not in used]
        if not pool:
            pool = [p for p in bat if p not in used]
        pick = max(pool, key=lambda p: bat[p]["ops"] * (0.4 + 0.6 * bat[p]["health"]))
        assign[slot] = pick
        used.add(pick)
    assign[9] = max(pit, key=lambda p: (1.0 / (pit[p]["era"] + 1.0))
                    * min(pit[p]["stamina"] / 45.0, 1.0) * (0.15 + 0.85 * pit[p]["health"]))
    return assign


def tabu_defense(bat, pit, rng: random.Random):
    cur = _legal_defense(bat, pit, rng)
    best, best_val = list(cur), defense_fitness(cur, bat, pit)
    tabu = {}          # (pcode, slot) -> 금지 해제 iteration
    bench = [p for p in bat]
    pitchers = list(pit)

    for it in range(TS_ITERS_DEFENSE):
        cand_best, cand_val, cand_move = None, float("-inf"), None
        in_use = set(cur)
        for _ in range(NEIGHBORS_PER_ITER):
            nxt = list(cur)
            if rng.random() < 0.5:
                # (a) 두 칸 맞바꾸기 — 투수 칸은 제외
                i, j = rng.sample(range(9), 2)
                nxt[i], nxt[j] = nxt[j], nxt[i]
                move = (nxt[i], i)
            elif rng.random() < 0.75:
                # (b) 한 칸을 벤치 선수로 교체
                i = rng.randrange(9)
                pool = [p for p in bench if p not in in_use]
                if not pool:
                    continue
                nxt[i] = rng.choice(pool)
                move = (nxt[i], i)
            else:
                # (c) 투수 교체
                nxt[9] = rng.choice(pitchers)
                move = (nxt[9], 9)
            val = defense_fitness(nxt, bat, pit)
            is_tabu = tabu.get(move, -1) > it
            if is_tabu and val <= best_val:      # 열망 기준: 최고해를 넘으면 타부 무시
                continue
            if val > cand_val:
                cand_best, cand_val, cand_move = nxt, val, move
        if cand_best is None:
            continue
        cur = cand_best
        tabu[cand_move] = it + TABU_TENURE
        if cand_val > best_val:
            best, best_val = list(cur), cand_val
    return best


# ---------------------------------------------------------------- 공격 평가
SLOT_OBP_W = [1.6, 1.5, 1.1, 1.0, 1.0, 0.9, 0.8, 0.8, 0.7]
SLOT_SLG_W = [0.8, 0.9, 1.3, 1.5, 1.4, 1.1, 1.0, 0.9, 0.8]


def offense_fitness(order, bat, start_index):
    score = 0.0
    for i, pcode in enumerate(order):
        b = bat[pcode]
        # 이번 이닝에 실제로 먼저 타석에 서는 순서일수록 가중치를 조금 더 준다
        turn = (i - start_index) % 9
        urgency = 1.0 + 0.25 * (1.0 - turn / 9.0)
        score += (b["obp"] * SLOT_OBP_W[i] + b["slg"] * SLOT_SLG_W[i]) \
            * (0.6 + 0.4 * b["health"]) * urgency
    return score


def tabu_offense(candidates, bat, start_index, rng: random.Random):
    cur = sorted(candidates, key=lambda p: bat[p]["ops"], reverse=True)
    best, best_val = list(cur), offense_fitness(cur, bat, start_index)
    tabu = {}
    for it in range(TS_ITERS_OFFENSE):
        cand_best, cand_val, cand_move = None, float("-inf"), None
        for _ in range(NEIGHBORS_PER_ITER):
            i, j = rng.sample(range(9), 2)
            nxt = list(cur)
            nxt[i], nxt[j] = nxt[j], nxt[i]
            move = tuple(sorted((nxt[i], nxt[j])))
            val = offense_fitness(nxt, bat, start_index)
            if tabu.get(move, -1) > it and val <= best_val:
                continue
            if val > cand_val:
                cand_best, cand_val, cand_move = nxt, val, move
        if cand_best is None:
            continue
        cur = cand_best
        tabu[cand_move] = it + TABU_TENURE
        if cand_val > best_val:
            best, best_val = list(cur), cand_val
    return best


# ---------------------------------------------------------------- 제출 함수
def decide_lineup(is_offense: bool, my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                   matchups: pd.DataFrame, context: dict, rng: random.Random):
    bat, pit = build_profiles(my_team)

    if not is_offense:
        return tabu_defense(bat, pit, rng)

    # 공격: 최소 출전 기준을 넘긴 선수 중 상위 9명을 후보로 두고 타순을 Tabu Search로 최적화
    qualified = [p for p, v in bat.items() if v["pa"] >= QUALIFY_PA]
    rest = [p for p in bat if p not in set(qualified)]
    qualified.sort(key=lambda p: bat[p]["ops"] * (0.35 + 0.65 * bat[p]["health"]), reverse=True)
    rest.sort(key=lambda p: bat[p]["pa"], reverse=True)
    candidates = (qualified + rest)[:9]
    return tabu_offense(candidates, bat, context.get("batting_order_start_index", 0), rng)
