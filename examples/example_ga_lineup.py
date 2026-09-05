"""
example_ga_lineup.py
----------------------
실제로 동작하는 유전 알고리즘(GA) 예제 제출물. 수업에서 배운 GA를 "공격 타순 최적화"에
적용하는 완결된 예시로, 학생들이 본인 알고리즘을 설계할 때 참고할 수 있도록 만들었다.
(그대로 제출해도 동작은 하지만, 평가 함수가 매우 단순하므로 그대로 내면 좋은 점수를 받기
어렵다 - 어디까지나 "이런 식으로 GA를 끼워넣으면 된다"는 참고용 예제)

- 개체(individual) = 9명 타자의 순열(타순)
- 적합도 = 전통적인 "타순 가중치"(1~2번은 출루, 3~5번은 장타력 비중) 휴리스틱으로
  근사한 기대 득점 점수. 실제 시뮬레이션을 여러 번 돌려 적합도를 매기면 훨씬 정확하지만
  10초 제한 안에서는 비용이 크므로(사전 벤치마크 참고), 여기서는 폐쇄형 근사식을 사용한다.
- population=40, generations=60 정도로 제한해 10초 제한에 여유 있게 들어오도록 함.

수비 라인업은 GA를 적용할 만큼 자유도가 크지 않아(포지션 제약이 강함) 간단한 그리디 배정으로
처리했다 - 이 부분을 Tabu Search 등으로 바꿔보는 것도 좋은 연습이 된다.

이닝 선발 규칙: 수비 호출에서 투수 포함 10명을 선발합니다. 공격 호출의 my_team은 그 10명만
포함하므로, 투수 제외 9명의 타순만 정하세요. context["selected_lineup"]은 수비 자리 순서의
선발 10명입니다. 공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다.
"""
import random

import pandas as pd

POP_SIZE = 40
GENERATIONS = 60
TOURNAMENT_K = 3
MUTATION_RATE = 0.15

# 타순 위치별 대략적인 가중치 (1~2번=출루/스피드, 3~5번=장타, 6~9번=평균 이하 비중)
SLOT_OBP_WEIGHT = [1.6, 1.5, 1.1, 1.0, 1.0, 0.9, 0.8, 0.8, 0.7]
SLOT_SLG_WEIGHT = [0.8, 0.9, 1.3, 1.5, 1.4, 1.1, 1.0, 0.9, 0.8]


LEAGUE_OBP, LEAGUE_SLG, LEAGUE_OPS = 0.350, 0.400, 0.750
SHRINK_PA = 80.0    # 표본이 이 정도는 돼야 그 선수의 기록을 그대로 믿는다
QUALIFY_PA = 50     # 이 정도 타석은 소화해야 '주전 후보'로 본다 (실제 야구의 규정타석 개념)
# 참고: 축소보정(shrinkage)만으로는 "1타석 1안타 → OPS 4.000" 같은 극단값을 완전히 못 누른다.
# 가중치가 1%여도 4.000이라는 값 자체가 워낙 커서 평균을 밀어올리기 때문. 그래서 실제 분석에서
# 늘 하듯 '최소 출전 기준'을 함께 건다.


def _num(v, default):
    """v가 없거나(None) 결측(NaN)이면 default, 0.0처럼 유효한 실측값이면 그대로 반환한다.
    `row.get(col) or default`로 쓰면 진짜 0인 값(OPS 0.000, ERA 0.00, health_pct 0 등)까지
    "없는 값" 취급해 default로 바꿔버리는 버그가 생긴다 (파이썬에서 0은 falsy이기 때문)."""
    return default if pd.isna(v) else v


def reliable(row, col, league_avg):
    """표본(PA)이 적은 선수의 기록을 리그 평균 쪽으로 당겨서 보정한다.
    이걸 안 하면 '1타석 1안타 → OPS 4.000' 같은 선수가 최고 타자로 뽑혀버린다.
    (시뮬레이션 엔진도 내부적으로 같은 방식의 축소보정을 쓴다)"""
    pa = float(_num(row.get("PA"), 0.0))
    val = float(_num(row.get(col), league_avg))
    w = pa / (pa + SHRINK_PA)
    return w * val + (1 - w) * league_avg


def _lineup_fitness(order, stat_by_pcode):
    score = 0.0
    for i, pcode in enumerate(order):
        row = stat_by_pcode[pcode]
        obp = reliable(row, "OBP", LEAGUE_OBP)
        slg = reliable(row, "SLG", LEAGUE_SLG)
        health = _num(row.get("health_pct"), 100.0) / 100.0
        score += (obp * SLOT_OBP_WEIGHT[i] + slg * SLOT_SLG_WEIGHT[i]) * (0.6 + 0.4 * health)
    return score


def _ga_batting_order(pcodes, stat_by_pcode, rng: random.Random):
    def random_individual():
        ind = list(pcodes)
        rng.shuffle(ind)
        return ind

    def tournament_select(pop_with_fitness):
        cand = rng.sample(pop_with_fitness, min(TOURNAMENT_K, len(pop_with_fitness)))
        return max(cand, key=lambda pf: pf[1])[0]

    def order_crossover(p1, p2):
        n = len(p1)
        a, b = sorted(rng.sample(range(n), 2))
        child = [None] * n
        child[a:b] = p1[a:b]
        fill = [g for g in p2 if g not in child[a:b]]
        idx = 0
        for i in range(n):
            if child[i] is None:
                child[i] = fill[idx]
                idx += 1
        return child

    def mutate(ind):
        if rng.random() < MUTATION_RATE:
            i, j = rng.sample(range(len(ind)), 2)
            ind[i], ind[j] = ind[j], ind[i]
        return ind

    population = [random_individual() for _ in range(POP_SIZE)]
    for _ in range(GENERATIONS):
        scored = [(ind, _lineup_fitness(ind, stat_by_pcode)) for ind in population]
        scored.sort(key=lambda pf: pf[1], reverse=True)
        next_gen = [scored[0][0]]  # 엘리트 보존
        while len(next_gen) < POP_SIZE:
            p1 = tournament_select(scored)
            p2 = tournament_select(scored)
            child = mutate(order_crossover(p1, p2))
            next_gen.append(child)
        population = next_gen

    best = max(population, key=lambda ind: _lineup_fitness(ind, stat_by_pcode))
    return best


def decide_lineup(is_offense: bool, my_team: pd.DataFrame, opponent_team: pd.DataFrame,
                   matchups: pd.DataFrame, context: dict, rng: random.Random):
    batters = my_team[my_team["role"] == "타자"]
    pitchers = my_team[my_team["role"] == "투수"]
    stat_by_pcode = {row["pCode"]: row for _, row in batters.iterrows()}
    pitcher_stat = {row["pCode"]: row for _, row in pitchers.iterrows()}

    # 타자 점수: 표본 보정한 OPS × 체력 (체력이 바닥난 선수는 벤치에 두는 게 낫다)
    def batter_value(pcode):
        row = stat_by_pcode[pcode]
        ops = reliable(row, "OPS", LEAGUE_OPS)
        health = _num(row.get("health_pct"), 100.0) / 100.0
        return ops * (0.35 + 0.65 * health)

    def pick_best(pool, n):
        """최소 출전 기준을 넘긴 선수를 우선 쓰고, 모자라면 타석 많은 순으로 채운다."""
        qualified = [p for p in pool if float(stat_by_pcode[p].get("PA", 0) or 0) >= QUALIFY_PA]
        rest = [p for p in pool if p not in set(qualified)]
        qualified.sort(key=batter_value, reverse=True)
        rest.sort(key=lambda p: float(stat_by_pcode[p].get("PA", 0) or 0), reverse=True)
        return (qualified + rest)[:n]

    if is_offense:
        # 후보 9명을 추린 뒤 그 안에서 GA로 순서(타순)를 최적화
        candidates = pick_best(batters["pCode"].tolist(), 9)
        best_order = _ga_batting_order(candidates, stat_by_pcode, rng)
        return best_order

    def top_by_position(pos, n):
        pool = batters[batters["position"] == pos]["pCode"].tolist()
        return pick_best(pool, n)

    chosen_if = top_by_position("내야수", 4)
    chosen_of = top_by_position("외야수", 3)
    chosen_c = top_by_position("포수", 1)
    used = set(chosen_if) | set(chosen_of) | set(chosen_c)
    remaining = [p for p in batters["pCode"].tolist() if p not in used]
    dh_pick = pick_best(remaining, 1)
    dh = dh_pick[0] if dh_pick else batters["pCode"].tolist()[0]

    # ------------------------------------------------------------------
    # 투수 선택 - 여기서 초보자가 가장 많이 하는 실수가 "그냥 ERA 제일 낮은 투수"다.
    # 방어율이 0.00인 투수는 대개 몇 이닝 안 던진 불펜이라 표본도 못 믿을뿐더러,
    # 등판당 평균 투구수(NP_per_G)가 15구밖에 안 돼서 한 이닝만 길어져도 체력이 바닥나
    # 그대로 대량실점으로 이어진다. 그래서 아래 3가지를 함께 본다:
    #   (1) ERA를 이닝수로 축소보정 (표본이 적으면 리그평균 쪽으로 당김)
    #   (2) 스태미너 = 등판당 평균 투구수 (한 이닝을 감당할 수 있는가)
    #   (3) 현재 체력 (이미 지친 투수는 제외)
    # ------------------------------------------------------------------
    LEAGUE_ERA = 4.8

    def pitcher_score(pcode):
        row = pitcher_stat[pcode]
        ip = float(row.get("IP_f", 0) or 0)
        era = float(_num(row.get("ERA"), LEAGUE_ERA))
        health = _num(row.get("health_pct"), 100.0) / 100.0
        stamina = float(_num(row.get("NP_per_G"), 20.0))
        # (1) 표본 축소: 이닝이 적을수록 리그 평균 ERA 쪽으로
        w = ip / (ip + 30.0)
        era_adj = w * era + (1 - w) * LEAGUE_ERA
        quality = 1.0 / (era_adj + 1.0)
        # (2) 한 이닝(대략 15~20구)을 여유 있게 소화할 수 있는지
        stamina_factor = min(stamina / 40.0, 1.0)
        # (3) 지친 투수는 크게 감점
        return quality * (0.35 + 0.65 * stamina_factor) * (0.2 + 0.8 * health)

    pitcher = max(pitchers["pCode"].tolist(), key=pitcher_score)

    return chosen_if + chosen_of + chosen_c + [dh, pitcher]
