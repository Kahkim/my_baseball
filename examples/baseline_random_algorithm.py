"""
baseline_random_algorithm.py
-----------------------------
가장 단순한 "합법적인" 제출 예시. 메타휴리스틱이 전혀 없고 그냥 무작위로 유효한 라인업을
고른다. 엔진 테스트/시연용 baseline이며, 학생 제출물의 최소 스펙을 보여주는 참고용이다.
(진짜 학생 과제 템플릿은 examples/student_algorithm_template.py 참고)

이닝 선발 규칙: 수비 호출에서 투수 포함 10명을 선발합니다. 공격 호출의 my_team은 그 10명만
포함하므로, 투수 제외 9명의 타순만 정하세요. context["selected_lineup"]은 수비 자리 순서의
선발 10명입니다. 공수교대 때 선수·투수 교체는 없으며, 다음 이닝 시작에 다시 선발합니다.
"""
import random


def decide_lineup(is_offense, my_team, opponent_team, matchups, context, rng: random.Random):
    batters = my_team[my_team["role"] == "타자"]
    pitchers = my_team[my_team["role"] == "투수"]

    if is_offense:
        pool = batters["pCode"].tolist()
        rng.shuffle(pool)
        return pool[:9]

    ifs = batters[batters["position"] == "내야수"]["pCode"].tolist()
    ofs = batters[batters["position"] == "외야수"]["pCode"].tolist()
    cs = batters[batters["position"] == "포수"]["pCode"].tolist()
    rng.shuffle(ifs)
    rng.shuffle(ofs)
    rng.shuffle(cs)
    chosen_if = ifs[:4]
    chosen_of = ofs[:3]
    chosen_c = cs[:1]
    used = set(chosen_if) | set(chosen_of) | set(chosen_c)
    rest = [p for p in batters["pCode"].tolist() if p not in used]
    rng.shuffle(rest)
    dh = rest[0]
    pitcher_pool = pitchers["pCode"].tolist()
    rng.shuffle(pitcher_pool)
    pitcher = pitcher_pool[0]
    return chosen_if + chosen_of + chosen_c + [dh, pitcher]
