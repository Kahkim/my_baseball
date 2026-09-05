"""
fatigue.py
----------
체력 저하 모델 (요구사항 #4).

- 타자/야수: "20번 스윙"을 목표치로 설정. 배팅 스윙 + 수비 이닝(1이닝당 스윙 환산 3~5)이
  같은 스윙 카운트 풀(pool)을 공유한다. 회복 없음(경기 내내 누적).
- 투수: "실제 등판당 평균 투구수(NP/G)"를 목표치로 설정, ±20% 개인차 랜덤.
- 목표치 자체에 랜덤을 줘서 "잘하는 선수가 항상 잘하지 않도록" 개인차/경기차를 만든다
  (스펙 요구사항: 개인차는 목표치 자체에 랜덤).
- 능력치는 시그모이드로 목표치 부근에서 급락.

시그모이드: mult(count) = 1 - MAX_DROP / (1 + exp(-k * (count - target)))
  count << target  -> mult ≈ 1.0 (거의 정상)
  count == target   -> mult ≈ 1 - MAX_DROP/2 (절반 저하)
  count >> target   -> mult ≈ 1 - MAX_DROP (최대 저하, 완전히 0이 되지는 않음)

k는 target에 비례해 정해 목표치가 큰 선발투수는 완만하게, 목표치가 작은 불펜투수는
좁은 구간에서 급하게 떨어지도록 한다.
"""
from __future__ import annotations

import math
import random

BATTER_BASE_TARGET_SWINGS = 20.0
BATTER_TARGET_JITTER = 0.20        # 타자 목표치 개인차 (투수의 ±20% 규정을 동일 적용; 스펙에 타자 수치가
                                    # 명시되어 있지 않아 투수와 동일한 비율을 합리적 기본값으로 채택 - 문서화된 가정)
PITCHER_TARGET_JITTER = 0.20       # "투수는 실제 등판당 평균 투구수 기반 ±20%" (스펙 명시)

FIELDING_SWING_EQUIV_MIN = 3.0     # "야수의 1이닝 수비는 스윙 3~5번 체력저하"
FIELDING_SWING_EQUIV_MAX = 5.0

# 완전 탈진 시 최대 능력치 저하폭. tools/calibrate.py로 실측해서 정한 값이다:
#   - 투수를 이닝마다 교체하며 정상 운영하면 9이닝 4~5점 (KBO 실제 팀당 경기 득점 수준)
#   - 한 투수로 9이닝을 끝까지 끌면 10점 내외로 무너짐 (혹사에 대한 분명한 페널티)
# 이 값과 probability.FATIGUE_SKILL_ALPHA가 함께 체력 -> 실제 성적 저하 폭을 결정한다.
MAX_DROP = 0.50
STEEPNESS_NUMERATOR = 8.0          # k = STEEPNESS_NUMERATOR / target


def roll_batter_target(engine_rng: random.Random) -> float:
    lo = BATTER_BASE_TARGET_SWINGS * (1 - BATTER_TARGET_JITTER)
    hi = BATTER_BASE_TARGET_SWINGS * (1 + BATTER_TARGET_JITTER)
    return engine_rng.uniform(lo, hi)


def roll_pitcher_target(engine_rng: random.Random, base_target_pitches: float) -> float:
    lo = base_target_pitches * (1 - PITCHER_TARGET_JITTER)
    hi = base_target_pitches * (1 + PITCHER_TARGET_JITTER)
    return max(engine_rng.uniform(lo, hi), 10.0)


def roll_fielding_fatigue(engine_rng: random.Random) -> float:
    """야수가 수비로 1이닝을 나갔을 때 스윙 카운트 풀에 더해지는 '환산 스윙수'."""
    return engine_rng.uniform(FIELDING_SWING_EQUIV_MIN, FIELDING_SWING_EQUIV_MAX)


def performance_multiplier(count: float, target: float) -> float:
    if target <= 0:
        target = 1.0
    k = STEEPNESS_NUMERATOR / target
    x = k * (count - target)  # count > target 이면 x>0 -> sig->1(탈진), count < target 이면 x<0 -> sig->0(쌩쌩)
    # overflow 방지
    if x > 40:
        sig = 1.0
    elif x < -40:
        sig = 0.0
    else:
        sig = 1.0 / (1.0 + math.exp(-x))
    return 1.0 - MAX_DROP * sig


def health_pct(count: float, target: float) -> float:
    """UI에 보여줄 체력 %. performance_multiplier를 0~100% 스케일로 환산."""
    mult = performance_multiplier(count, target)
    floor = 1.0 - MAX_DROP
    # mult는 [floor, 1.0] 범위 -> 이를 [0,100]으로 선형 재매핑해 "완전탈진=0%, 쌩쌩=100%"로 표시
    pct = (mult - floor) / (1.0 - floor) * 100.0
    return max(0.0, min(100.0, pct))
