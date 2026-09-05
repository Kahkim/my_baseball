"""개선형 Tabu Search: 출전 10명 선발 + 타순 + 공수 체력 배분.

이 파일 하나만 제출할 수 있습니다. 엔진 import, 파일 접근, 전역 난수 없이
전달된 DataFrame과 rng만 사용합니다. 평가식은 실제 득점의 근사이며 승리를 보장하지 않습니다.

기존 예제와의 차이:
1. 선발 단계에서 벤치 교체·수비 배치를, 공격 단계에서 고정 9명의 타순을 탐색합니다.
2. 선발 9명이 공수를 함께 맡으므로 타격 기여와 수비 비용을 함께 평가합니다.
3. 투수의 pitch_count/target으로 한 이닝 중의 능력을 예측합니다.
4. 되돌아가는 배정을 타부로 기록하고, 최고해를 개선하면 열망 기준으로 허용합니다.

반복 수는 고정하므로 같은 입력/rng에서 결과가 재현됩니다.
상수는 학습용 가정이며, 팀별 기록과 맞대결 표본을 이용해 보정합니다.

이닝 선발 규칙: 수비 호출에서 투수 포함 10명을 선발합니다. 공격 호출의 my_team은 그 10명만
포함하므로, 투수 제외 9명의 타순만 정하세요. context["selected_lineup"]은 수비 자리 순서의
선발 10명입니다. 공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다.
"""
import math

import pandas as pd

# 사건 순서: BB, HBP, 1B, 2B, 3B, HR, SO, OUT.
# 동봉 데이터 전체를 읽는 대신 사용하는 일반적인 사전분포(합계 1).
PRIOR = (0.090, 0.015, 0.170, 0.045, 0.005, 0.025, 0.190, 0.460)
RUN_WEIGHTS = (0.70, 0.73, 0.90, 1.25, 1.60, 2.00, 0.0, 0.0)
POSITIONS = ("내야수",) * 4 + ("외야수",) * 3 + ("포수", "DH")
FIELD_SHARES = (0.115,) * 4 + (0.16,) * 3 + (0.0, 0.0)
ITERATIONS = 80
NEIGHBORS = 40
TENURE = 7


def _num(value, default=0.0):
    return default if pd.isna(value) else float(value)


def _rates(row, pitcher=False, shrink=None):
    """사건 횟수에 사전분포를 더해 적은 표본의 극단적인 기록을 완화합니다."""
    n = _num(row.get("TBF_eff" if pitcher else "PA_eff"),
             _num(row.get("TBF" if pitcher else "PA")))
    h, d, t, hr = (_num(row.get(k)) for k in ("H", "2B", "3B", "HR"))
    bb, hbp, so = (_num(row.get(k)) for k in ("BB", "HBP", "SO"))
    counts = (bb, hbp, max(h - d - t - hr, 0), d, t, hr, so,
              max(n - h - bb - hbp - so, 0))
    k = (80.0 if pitcher else 60.0) if shrink is None else shrink
    values = [max(c, 0) + k * prior for c, prior in zip(counts, PRIOR)]
    total = sum(values)
    return tuple(v / total for v in values)


def _mult(row, extra=0.0, pitcher=False):
    count = _num(row.get("pitch_count" if pitcher else "swing_count"))
    target = max(_num(row.get("pitch_target" if pitcher else "swing_target"),
                      50.0 if pitcher else 20.0), 1.0)
    x = max(-40.0, min(40.0, 8.0 * (count + extra - target) / target))
    return 1.0 - 0.5 / (1.0 + math.exp(-x))


def _match_rate(batter, pitcher, match=None):
    values = [b * p / prior for b, p, prior in zip(batter, pitcher, PRIOR)]
    total = sum(values)
    values = [v / total for v in values]
    if match is not None:
        pa = _num(match.get("PA"))
        if pa > 0:
            empirical = _rates(match, shrink=0.0)
            weight = pa / (pa + 15.0)
            values = [weight * e + (1 - weight) * v for e, v in zip(empirical, values)]
    return tuple(values)


def _production(rate, batter_mult=1.0, pitcher_mult=1.0):
    factor = (batter_mult / pitcher_mult) ** 0.6
    weights = [p * (factor if i < 6 else 1 / factor) for i, p in enumerate(rate)]
    total = sum(weights)
    probs = [p / total for p in weights]
    onbase = sum(probs[:6])
    value = sum(p * w for p, w in zip(probs, RUN_WEIGHTS))
    return value, onbase, sum(
        probs[i] * w for i, w in ((2, 1), (3, 2), (4, 3), (5, 4)))


def _tabu(initial, pool, slot_scores, rng, pair_bonus=None):
    """선수-슬롯 배정. 교환과 벤치 교체 모두 합법적인 이웃만 만듭니다."""
    def fitness(order):
        result = sum(slot_scores[i][p] for i, p in enumerate(order))
        if pair_bonus is not None:
            result += sum(pair_bonus(order[i], order[(i + 1) % 9], i) for i in range(9))
        return result

    current = list(initial)
    best = current[:]
    best_score = fitness(best)
    tabu_until = {}
    stagnant = 0
    for iteration in range(ITERATIONS):
        used = set(current)
        bench = [p for p in pool if p not in used]
        chosen, chosen_score, reverse = None, -float("inf"), []
        for _ in range(NEIGHBORS):
            candidate = current[:]
            if bench and rng.random() < 0.55:
                i = rng.randrange(9)
                candidate[i] = rng.choice(bench)
                slots = (i,)
            else:
                i, j = rng.sample(range(9), 2)
                candidate[i], candidate[j] = candidate[j], candidate[i]
                slots = (i, j)
            score = fitness(candidate)
            forbidden = any(tabu_until.get((candidate[i], i), -1) > iteration for i in slots)
            if forbidden and score <= best_score + 1e-12:
                continue
            if score > chosen_score:
                chosen, chosen_score = candidate, score
                reverse = [(current[i], i) for i in slots]
        if chosen is None:
            continue
        current = chosen
        # 들어온 선수 대신 빠진 선수를 같은 자리에 되돌리는 역이동을 금지합니다.
        for move in reverse:
            tabu_until[move] = iteration + TENURE + rng.randrange(3)
        stagnant += 1
        if chosen_score > best_score + 1e-12:
            best, best_score, stagnant = chosen[:], chosen_score, 0
        if stagnant >= 24:
            current = best[:]
            rng.shuffle(current)
            tabu_until.clear()
            stagnant = 0
    return best


def decide_lineup(is_offense, my_team, opponent_team, matchups, context, rng):
    mine = {int(r["pCode"]): r for r in my_team.to_dict("records")}
    opponents = {int(r["pCode"]): r for r in opponent_team.to_dict("records")}
    bat = {p: r for p, r in mine.items() if r["role"] == "타자"}
    pit = {p: r for p, r in mine.items() if r["role"] == "투수"}
    opp_bat = {p: r for p, r in opponents.items() if r["role"] == "타자"}
    matchup = {(int(r["pitcherPCode"]), int(r["hitterPCode"])): r
               for r in matchups.to_dict("records")}
    rates = {p: _rates(r) for p, r in bat.items()}
    inning = int(context.get("inning", 1))

    if is_offense:
        pitcher_id = context.get("opp_pitcher_pcode")
        pitcher = opponents.get(pitcher_id)
        pitcher_rates = _rates(pitcher, pitcher=True) if pitcher is not None else PRIOR
        pitcher_mult = _mult(pitcher, 10, True) if pitcher is not None else 1.0
        profiles = {}
        for p, row in bat.items():
            rate = _match_rate(rates[p], pitcher_rates, matchup.get((pitcher_id, p)))
            profiles[p] = _production(rate, _mult(row, 1.5), pitcher_mult)
        # 실제 선두부터 탐색한 뒤 엔진이 요구하는 타순 인덱스에 맞춰 반환합니다.
        start = int(context.get("batting_order_start_index", 0)) % 9
        slot_scores = []
        for turn in range(9):
            urgency = 1.0 - 0.045 * turn
            slot_scores.append({p: urgency * (v + 0.25 * obp) for p, (v, obp, slg) in profiles.items()})
        def pair_bonus(left, right, turn):
            return 0.09 * (1 - turn * 0.04) * profiles[left][1] * profiles[right][2]
        pool = sorted(bat)
        initial = sorted(pool, key=lambda p: slot_scores[0][p], reverse=True)[:9]
        ordered = _tabu(initial, pool, slot_scores, rng, pair_bonus)
        lineup = [0] * 9
        for turn, p in enumerate(ordered):
            lineup[(start + turn) % 9] = p
        return lineup

    # 선발한 9명이 공격도 맡으므로 타격 기여와 수비 체력 손실을 함께 계산합니다.
    value_now = {p: _production(rates[p], _mult(row))[0] for p, row in bat.items()}
    best_nine = sorted(value_now.values(), reverse=True)[:9]
    cutoff = best_nine[-1]
    conserve = 0.35 + 0.65 * max(9 - inning, 0) / 8
    # 홈팀은 이번 말 공격도 남아 있으므로 마지막 이닝에도 타자 보호 가치가 있습니다.
    if context.get("half") == "top":
        conserve = max(conserve, 0.6)
    slot_scores = []
    for slot, want in enumerate(POSITIONS):
        scores = {}
        for p, row in bat.items():
            if want == "DH":
                scores[p] = 0.55 * value_now[p]
                continue
            future_loss = max(value_now[p] - _production(rates[p], _mult(row, 4))[0], 0)
            relevance = min(1.0, (value_now[p] / max(cutoff, 0.01)) ** 4)
            # 개인 실책 성향은 입력에 없으므로 평균적인 실책 비용만 근사합니다.
            base_error = 0.022 if want == "내야수" else 0.014
            mismatch = 1.0 if row["position"] == want else 1.5
            error_cost = 4.0 * FIELD_SHARES[slot] * base_error * mismatch * (2 - _mult(row, 4))
            scores[p] = 0.55 * (value_now[p] - future_loss) - error_cost - 0.45 * conserve * relevance * future_loss
        slot_scores.append(scores)
    pool = sorted(bat)
    initial, used = [], set()
    for scores in slot_scores:
        pick = max((p for p in pool if p not in used), key=lambda p: scores[p])
        initial.append(pick)
        used.add(pick)
    fielders = _tabu(initial, pool, slot_scores, rng)

    # 상대의 직전 타순에만 의존하지 않고 출전할 가능성이 큰 상위 9명을 예측합니다.
    opp_rates = {p: _rates(row) for p, row in opp_bat.items()}
    likely = sorted(opp_bat, key=lambda p: _production(opp_rates[p], _mult(opp_bat[p]))[0],
                    reverse=True)[:9]
    def pitcher_cost(p):
        row = pit[p]
        prate = _rates(row, pitcher=True)
        total = 0.0
        for hitter in likely:
            combined = _match_rate(opp_rates[hitter], prate, matchup.get((p, hitter)))
            for extra in (4, 12, 22):
                value, onbase, _ = _production(combined, _mult(opp_bat[hitter], 1), _mult(row, extra, True))
                total += value / max(1.0 - onbase, 0.15)
        return total
    # 투수 선택은 야수 배정과 독립이므로 모든 투수를 직접 비교합니다.
    pitcher = min(sorted(pit), key=pitcher_cost)
    return fielders + [pitcher]
