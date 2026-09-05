"""
strategy_fatigue_rotation.py
-----------------------------
메타휴리스틱 없이 **체력 관리 규칙 하나만** 지키는 대조군.

이 게임에서 가장 큰 승부처가 무엇인지 보여주기 위한 참고 구현이다. 탐색 알고리즘은 전혀 쓰지
않고 다음 세 가지 규칙만 지킨다:

  1. 투수는 체력이 남아 있고 스태미너(등판당 평균 투구수)가 충분한 사람 중 **가장 덜 지친** 투수
  2. 야수는 포지션이 맞는 선수 중 체력 가중 점수 상위 → 지친 선수는 자동으로 벤치로 내려감
  3. 타순은 체력 가중 OPS 순 (출루형 앞, 장타형 중심)

수업에서 이 대조군과 학생의 GA/TS/PSO를 비교해 보면,
"탐색 알고리즘이 규칙 기반 휴리스틱을 실제로 이기는가?"를 정량적으로 확인할 수 있다.
(이기지 못한다면 적합도 함수가 게임의 실제 승리 요인을 반영하지 못하고 있다는 뜻이다)
"""
import random

import pandas as pd

LEAGUE_OPS, LEAGUE_ERA = 0.750, 4.80
SHRINK_PA, SHRINK_IP = 80.0, 30.0
QUALIFY_PA = 40


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
    rows = my_team.to_dict("records")
    bat = {}
    pit = {}
    for r in rows:
        health = (r.get("health_pct") if r.get("health_pct") is not None else 100) / 100.0
        if r["role"] == "타자":
            bat[r["pCode"]] = {
                "pos": r["position"], "health": health, "pa": float(r.get("PA", 0) or 0),
                "ops": _shrunk(r, "OPS", LEAGUE_OPS, "PA", SHRINK_PA),
                "obp": _shrunk(r, "OBP", 0.350, "PA", SHRINK_PA),
                "slg": _shrunk(r, "SLG", 0.400, "PA", SHRINK_PA),
            }
        else:
            pit[r["pCode"]] = {
                "health": health,
                "era": _shrunk(r, "ERA", LEAGUE_ERA, "IP_f", SHRINK_IP),
                "stamina": float(_num(r.get("NP_per_G"), 20.0)),
                "pitches": float(r.get("pitch_count") or 0),
            }

    # 체력을 강하게 반영한 타자 점수 (지친 선수는 확 떨어뜨린다)
    def bval(p):
        b = bat[p]
        base = b["ops"] if b["pa"] >= QUALIFY_PA else b["ops"] * 0.75
        return base * (0.15 + 0.85 * b["health"])

    if is_offense:
        order = sorted(bat, key=bval, reverse=True)[:9]
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
        chosen = sorted(pool, key=bval, reverse=True)[:n]
        used.update(chosen)
        return chosen

    ifs, ofs, cs = pick("내야수", 4), pick("외야수", 3), pick("포수", 1)
    dh = sorted([p for p in bat if p not in used], key=bval, reverse=True)[:1]

    # 투수: 아직 여력이 있는 투수 중 스태미너·실력을 함께 본 점수 1위.
    #       이미 많이 던져 지친 투수는 자동으로 후순위가 되어 자연스럽게 교대가 일어난다.
    def pval(p):
        v = pit[p]
        quality = 1.0 / (v["era"] + 1.0)
        stamina = min(v["stamina"] / 45.0, 1.0)
        return quality * (0.25 + 0.75 * stamina) * (v["health"] ** 1.5)

    ace = max(pit, key=pval)
    return ifs + ofs + cs + dh + [ace]
