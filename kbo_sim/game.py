"""
game.py
-------
9이닝 단일 경기 엔진.

두 가지 실행 방식을 모두 지원한다:
  (A) 배치 실행  : Game.run()          - 9이닝을 끝까지 한 번에 시뮬레이션 (CLI/채점용)
  (B) 스텝 실행  : Game.play_next_half() - 하프이닝 하나만 진행하고 즉시 반환 (라이브 중계용)
두 방식은 같은 상태머신을 쓰므로 같은 시드면 결과가 완전히 동일하다.

하프이닝마다:
  1) 수비팀 학생 알고리즘 호출 (is_offense=False) -> 수비 10명 결정 (마지막이 투수)
  2) 공격팀 학생 알고리즘 호출 (is_offense=True, 방금 정해진 상대 투수/포수 정보 포함)
     -> 타순 9명 결정
  3) 수비 진출 시 야수 체력(스윙환산 3~5) 1회 소모
  4) batting_order_start_index부터 타순을 순회하며 3아웃까지 타석 진행
  5) 10점 이상 차이나면 콜드게임 (mercy_min_inning 이닝 이후)
  6) 매 알고리즘 호출의 실행시간을 기록 (스코어보드 하단 표시용)

학생 알고리즘이 여러 번 호출되어도(같은 상황 재호출 등) 항상 안전하도록, 팀별 상태
(GameRosterState의 체력, 타순 포인터)는 이닝이 바뀌어도 계속 유지된다.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import fatigue
from .atbat import empty_bases, resolve_plate_appearance
from .data_pipeline import LeagueData
from .defense import DEFENSE_SLOT_GROUPS
from .models import GameRosterState, Team
from .rng import GameRNG
from .student_api import (default_defense_lineup, default_offense_lineup, matchup_dataframe,
                           run_student_decision, team_status_dataframe, validate_lineup)

MERCY_MARGIN = 10          # "10점이상이면 이닝 콜드게임 선언" (스펙 명시값)
MERCY_MIN_INNING = 5       # 스펙에 최소 이닝 명시가 없어 채택한 기본값(문서화된 가정) - 강사가 조정 가능
REGULATION_INNINGS = 9

# 수비 라인업 10칸의 화면 표시용 라벨 (defense.DEFENSE_SLOT_GROUPS와 1:1 대응)
DEFENSE_SLOT_LABELS = ["내야수", "내야수", "내야수", "내야수", "외야수", "외야수", "외야수",
                        "포수", "지명타자", "투수"]


@dataclass
class InningTiming:
    inning: int
    half: str
    team: str
    role: str  # 'offense'/'defense'
    status: str
    elapsed_sec: float


class Game:
    def __init__(self, league: LeagueData, home: Team, away: Team, algo_path: Dict[str, str],
                 seed: Optional[int] = None, timeout_sec: float = 10.0,
                 mercy_margin: int = MERCY_MARGIN, mercy_min_inning: int = MERCY_MIN_INNING,
                 max_innings: int = REGULATION_INNINGS, verbose_progress: bool = False):
        self.league = league
        self.home = home
        self.away = away
        self.algo_path = algo_path  # {team_name: filepath}
        self.grng = GameRNG(seed)
        self.roster_state = GameRosterState(league, self.grng.seed)
        self.timeout_sec = timeout_sec
        self.mercy_margin = mercy_margin
        self.mercy_min_inning = mercy_min_inning
        self.max_innings = max_innings
        self.verbose_progress = verbose_progress

        self.score = {home.name: 0, away.name: 0}
        self.hits = {home.name: 0, away.name: 0}
        self.errors = {home.name: 0, away.name: 0}
        self.next_batter_slot = {home.name: 0, away.name: 0}
        self.prev_lineup = {home.name: {"offense": None, "defense": None},
                             away.name: {"offense": None, "defense": None}}
        self.events: List[dict] = []
        self.timings: List[InningTiming] = []
        self.result: Optional[dict] = None

        # --- 스텝 실행용 진행 상태 ---
        self.current_inning = 1
        self.current_half = "top"      # 'top'(초, 원정팀 공격) / 'bottom'(말, 홈팀 공격)
        self.finished = False
        self.mercy_triggered = False
        self.final_inning = 0
        self._last_decisions: Dict[str, dict] = {}
        # 라인업만 먼저 뽑아두고 타석은 아직 진행하지 않은 상태를 담는다
        # (라이브 중계에서 "다음 라인업 선발" -> "다음 공격 진행" 2단계로 나누기 위함)
        self._pending: Optional[dict] = None

    # ------------------------------------------------------------------
    def _emit(self, ev: dict):
        self.events.append(ev)
        if self.verbose_progress:
            print(ev.get("text", ev.get("type")))

    def _display(self, pcode: int) -> str:
        """중계 화면에 쓰는 짧은 이름 (동명이인일 때만 등번호가 붙음).
        pCode가 진짜 키이고, '팀명+등번호+이름'(displayId)은 별도 필드로 계속 유지된다."""
        return self.league.player(int(pcode))["shortName"]

    def _lineup_detail(self, lineup: List[int], is_offense: bool, start_index: int = 0) -> List[dict]:
        """뷰어에 출전명단을 제대로 보여주기 위한 상세 정보(이름/포지션/체력/포지션 불일치 여부)."""
        out = []
        for i, pcode in enumerate(lineup):
            rec = self.league.player(int(pcode))
            rt = self.roster_state.get(pcode)
            item = {
                "index": i,
                "pCode": int(pcode),
                "name": rec["name"],
                "shortName": rec["shortName"],
                "displayId": rec["displayId"],
                "backNo": rec.get("backNo"),
                "real_position": rec["position"],
                "health": round(rt.health_pct(), 1),
            }
            if is_offense:
                # 타순 번호: start_index부터 실제로 타석에 들어서는 순서
                item["slot_label"] = f"{i + 1}번"
                item["bats_order"] = ((i - start_index) % 9) + 1
                item["is_leadoff"] = (i == start_index)
                item["OPS"] = rec.get("OPS")
            else:
                group = DEFENSE_SLOT_GROUPS[i]
                item["slot_label"] = DEFENSE_SLOT_LABELS[i]
                item["assigned_group"] = group
                item["mismatch"] = (group in ("내야수", "외야수", "포수")
                                     and group != rec["position"])
                if group == "투수":
                    item["pitch_count"] = round(rt.pitch_count, 1)
                    item["pitch_target"] = round(rt.pitch_target or 0, 1)
                    item["ERA"] = rec.get("ERA")
                else:
                    item["OPS"] = rec.get("OPS")
            out.append(item)
        return out

    def _team(self, name: str) -> Team:
        return self.home if name == self.home.name else self.away

    # ------------------------------------------------------------------
    def _decide(self, team: Team, opponent: Team, is_offense: bool, inning: int, half: str,
                start_index: int, opp_pitcher: Optional[int], opp_catcher: Optional[int]) -> List[int]:
        my_df = team_status_dataframe(self.league, team, self.roster_state)
        opp_df = team_status_dataframe(self.league, opponent, self.roster_state)
        if is_offense:
            mu_df = matchup_dataframe(self.league, [opp_pitcher] if opp_pitcher else [], team.batter_pcodes)
        else:
            mu_df = matchup_dataframe(self.league, team.pitcher_pcodes, opponent.batter_pcodes)

        context = {
            "inning": inning, "half": half,
            "my_score": self.score[team.name], "opponent_score": self.score[opponent.name],
            "outs": 0,
            "batting_order_start_index": start_index,
            "my_prev_lineup": self.prev_lineup[team.name]["offense" if is_offense else "defense"],
            "opponent_prev_lineup": self.prev_lineup[opponent.name]["defense" if is_offense else "offense"],
            "opp_pitcher_pcode": opp_pitcher if is_offense else None,
            "opp_catcher_pcode": opp_catcher if is_offense else None,
            "time_budget_sec": self.timeout_sec,
        }
        student_rng = self.grng.student_rng(f"{team.name}:{'off' if is_offense else 'def'}")
        module_name = f"student_{uuid.uuid4().hex[:8]}"

        t0 = time.time()
        outcome = run_student_decision(self.algo_path[team.name], module_name, is_offense=is_offense,
                                        my_team=my_df, opponent_team=opp_df, matchups=mu_df,
                                        context=context, rng=student_rng, timeout_sec=self.timeout_sec)
        elapsed = outcome.elapsed if outcome.elapsed else (time.time() - t0)

        lineup = outcome.lineup
        status = outcome.status
        err = outcome.error
        if status == "ok":
            try:
                problem = validate_lineup(self.league, team, lineup, is_offense)
            except Exception as e:  # noqa: BLE001 - 검증 중 무슨 예외가 나든 경기가 멈추면 안 됨
                problem = f"명단 검증 중 오류: {type(e).__name__}: {e}"
            if problem:
                status = "invalid"
                err = problem
                lineup = None

        role = "offense" if is_offense else "defense"
        if lineup is None:
            fallback = self.prev_lineup[team.name][role]
            try:
                fallback_ok = bool(fallback) and validate_lineup(self.league, team, fallback, is_offense) is None
            except Exception:  # noqa: BLE001
                fallback_ok = False
            if fallback_ok:
                lineup = fallback
                fallback_src = "직전 라인업 재사용"
            else:
                lineup = default_offense_lineup(team) if is_offense else default_defense_lineup(team)
                fallback_src = "기본 출전(명단 순서상 앞쪽 선수)"
            self._emit({"type": "algo_fallback", "inning": inning, "half": half, "team": team.name,
                        "role": role, "status": status, "error": err, "fallback": fallback_src,
                        "text": f"[{team.name}] 알고리즘 {status} ({err}) -> {fallback_src}"})
        else:
            lineup = [int(x) for x in lineup]

        self.prev_lineup[team.name][role] = lineup
        self.timings.append(InningTiming(inning=inning, half=half, team=team.name, role=role,
                                          status=status, elapsed_sec=elapsed))
        self._last_decisions[f"{team.name}|{role}"] = {
            "team": team.name, "role": role, "status": status,
            "elapsed_sec": round(elapsed, 3), "error": err}
        self._emit({"type": "lineup_decision", "inning": inning, "half": half, "team": team.name,
                    "role": role, "status": status, "elapsed_sec": round(elapsed, 3), "lineup": lineup,
                    "text": f"[{inning}회{'초' if half=='top' else '말'}] {team.name} "
                            f"{'공격' if is_offense else '수비'} 라인업 결정 ({elapsed:.2f}초)"})
        return lineup

    # ------------------------------------------------------------------
    # 1단계: 라인업 선발 — 이닝이 시작될 때 딱 한 번, 양 팀의 공격/수비 명단을 모두 정한다
    #        (학생 알고리즘 4회 호출: 두 팀 × 공격/수비. 초/말 공수교대 때는 다시 뽑지 않는다)
    # ------------------------------------------------------------------
    def prepare_next_inning(self) -> dict:
        if self.finished:
            return {"prepared": False, "finished": True, "events": [], "result": self.result}
        if self._pending is not None:
            return {"prepared": False, "already": True, "events": [],
                    "inning": self._pending["inning"]}

        cursor = len(self.events)
        inning = self.current_inning
        self._last_decisions = {}
        start_top = self.next_batter_slot[self.away.name]     # 초 공격 = 원정팀
        start_bot = self.next_batter_slot[self.home.name]      # 말 공격 = 홈팀

        # (1) 두 팀의 수비 라인업을 먼저 확정해 투수/포수를 정한다
        home_def = self._decide(self.home, self.away, False, inning, "top", start_top, None, None)
        away_def = self._decide(self.away, self.home, False, inning, "bottom", start_bot, None, None)
        # (2) 그 정보를 담아 두 팀의 공격 타순을 정한다
        #     (초 공격팀은 홈팀 투수를, 말 공격팀은 원정팀 투수를 상대한다)
        away_off = self._decide(self.away, self.home, True, inning, "top", start_top,
                                 home_def[9], home_def[7])
        home_off = self._decide(self.home, self.away, True, inning, "bottom", start_bot,
                                 away_def[9], away_def[7])

        lineups = {
            self.home.name: {"offense": home_off, "defense": home_def, "start_idx": start_bot},
            self.away.name: {"offense": away_off, "defense": away_def, "start_idx": start_top},
        }
        self._pending = {"inning": inning, "lineups": lineups}

        self._emit({
            "type": "inning_lineup", "inning": inning, "score": dict(self.score),
            "teams": {
                t: {
                    "offense": self._lineup_detail(lineups[t]["offense"], True, lineups[t]["start_idx"]),
                    "defense": self._lineup_detail(lineups[t]["defense"], False),
                    "start_index": lineups[t]["start_idx"],
                } for t in (self.away.name, self.home.name)
            },
            "decisions": dict(self._last_decisions),
            "text": f"=== {inning}회 출전명단 확정 — "
                    f"{self.away.name} 선두 {self._display(away_off[start_top % 9])} / "
                    f"{self.home.name} 선두 {self._display(home_off[start_bot % 9])} ==="})

        return {"prepared": True, "inning": inning, "events": self.events[cursor:], "finished": False}

    # 예전 이름 호환 (하프이닝마다 부르던 시절의 API)
    def prepare_next_half(self) -> dict:
        return self.prepare_next_inning()

    # ------------------------------------------------------------------
    # 2단계: 확정된 명단으로 다음 하프이닝의 공격을 진행
    # ------------------------------------------------------------------
    def play_prepared_half(self) -> dict:
        if self.finished:
            return {"played": False, "finished": True, "events": [], "result": self.result}
        if self._pending is None:
            self.prepare_next_inning()
        cursor = len(self.events)
        inning, half = self.current_inning, self.current_half
        batting, fielding = ((self.away, self.home) if half == "top" else (self.home, self.away))
        lineups = self._pending["lineups"]
        defense_lineup = lineups[fielding.name]["defense"]
        batting_order = lineups[batting.name]["offense"]
        start_idx = self.next_batter_slot[batting.name]
        pitcher_pcode, catcher_pcode = defense_lineup[9], defense_lineup[7]

        # 수비 진출 야수 체력 소모 — 실제로 필드에 나가는 이 시점에 적용
        for idx in range(0, 8):
            self.roster_state.get(defense_lineup[idx]).swing_count += \
                fatigue.roll_fielding_fatigue(self.grng.engine)

        self._emit({
            "type": "half_start", "inning": inning, "half": half,
            "batting_team": batting.name, "fielding_team": fielding.name,
            "pitcher": pitcher_pcode, "catcher": catcher_pcode,
            "score": dict(self.score),
            "batting_order_start_index": start_idx,
            "batting_order": self._lineup_detail(batting_order, True, start_idx),
            "defense": self._lineup_detail(defense_lineup, False),
            "decisions": {
                "offense": self._last_decisions.get(f"{batting.name}|offense"),
                "defense": self._last_decisions.get(f"{fielding.name}|defense"),
            },
            "health": self.roster_state.health_snapshot(batting_order + defense_lineup),
            "text": f"--- {inning}회{'초' if half=='top' else '말'} {batting.name} 공격 "
                    f"(선두타자 {self._display(batting_order[start_idx % 9])}) ---"})

        self._play_at_bats(inning, half, batting, fielding, defense_lineup, batting_order, start_idx)
        self._advance_schedule()
        # 이닝이 끝났으면(다음이 새 이닝의 '초'이거나 경기 종료) 확정 명단을 비운다
        if self.finished or self.current_half == "top":
            self._pending = None
        return {
            "played": True, "inning": inning, "half": half,
            "batting_team": batting.name, "fielding_team": fielding.name,
            "events": self.events[cursor:], "finished": self.finished,
            "next_inning": None if self.finished else self.current_inning,
            "next_half": None if self.finished else self.current_half,
            "score": dict(self.score), "result": self.result,
        }

    # ------------------------------------------------------------------
    def _play_at_bats(self, inning: int, half: str, batting: Team, fielding: Team,
                       defense_lineup: List[int], batting_order: List[int], start_idx: int):
        pitcher_pcode = defense_lineup[9]
        bases = empty_bases()
        outs = 0
        runs_this_half = 0
        slot = start_idx
        pa_count = 0

        while outs < 3:
            batter_pcode = batting_order[slot % 9]
            res = resolve_plate_appearance(self.league, batter_pcode, pitcher_pcode, defense_lineup,
                                            self.roster_state, self.grng.engine, bases, outs)
            for se in res.steal_events:
                self._emit({"type": "steal", "inning": inning, "half": half, **se})
            outs += res.outs_added
            runs_this_half += res.runs
            self.score[batting.name] += res.runs
            if res.event in ("1B", "2B", "3B", "HR"):
                self.hits[batting.name] += 1
            if res.error:
                self.errors[fielding.name] += 1

            for pitch in res.pitches:
                self._emit({"type": "pitch", "inning": inning, "half": half, "batter": batter_pcode,
                            "pitcher": pitcher_pcode, **pitch})

            self._emit({"type": "pa_result", "inning": inning, "half": half, "batter": batter_pcode,
                        "batter_name": self._display(batter_pcode), "pitcher": pitcher_pcode,
                        "pitcher_name": self._display(pitcher_pcode),
                        "event": res.event, "description": res.description,
                        "runs": res.runs, "rbi": res.rbi, "outs": min(outs, 3), "bases": dict(bases),
                        "score": dict(self.score),
                        "batter_health": round(self.roster_state.get(batter_pcode).health_pct(), 1),
                        "pitcher_health": round(self.roster_state.get(pitcher_pcode).health_pct(), 1),
                        "pitch_count": round(self.roster_state.get(pitcher_pcode).pitch_count, 1),
                        # 그라운드 시각화용 (경기 결과에는 영향 없음)
                        "fielder": res.fielder_pcode,
                        "fielder_name": self._display(res.fielder_pcode) if res.fielder_pcode else None,
                        "bip_type": res.bip_type, "hit_dir": res.hit_dir, "hit_depth": res.hit_depth,
                        "is_error": res.error,
                        "text": f"{self._display(batter_pcode)} : {res.description}"})

            # 도루자가 3아웃째로 잡혀 타석 자체가 중단된 경우, 그 타자는 타석을 소화하지 않았으므로
            # 타순을 넘기지 않는다 (야구규칙 5.04(a)(2): 다음 이닝 선두타자로 나온다)
            if res.event != "CS_INNING_END":
                pa_count += 1
                slot += 1

            if outs >= 3:
                break
            # 끝내기: 마지막 정규이닝 말에 홈팀이 역전하면 그 순간 경기 종료 (야구규칙 5.08(b))
            if (half == "bottom" and inning >= self.max_innings
                    and self.score[self.home.name] > self.score[self.away.name]):
                self._emit({"type": "walkoff", "inning": inning, "half": half,
                            "text": f"끝내기! {self.home.name}가 결승점을 뽑아 경기가 즉시 종료됩니다."})
                break

        self.next_batter_slot[batting.name] = (start_idx + pa_count) % 9
        self._emit({"type": "half_end", "inning": inning, "half": half, "batting_team": batting.name,
                    "runs": runs_this_half, "score": dict(self.score),
                    "hits": dict(self.hits), "errors": dict(self.errors),
                    "text": f"{inning}회{'초' if half=='top' else '말'} 종료 - {batting.name} {runs_this_half}득점 "
                            f"(스코어 {self.away.name} {self.score[self.away.name]} : "
                            f"{self.home.name} {self.score[self.home.name]})"})

    def _check_mercy(self, inning: int, half: str = "") -> bool:
        """콜드게임 조건. 하프이닝이 **끝난 뒤에만** 평가한다 (이닝 도중에 끊지 않음)."""
        diff = abs(self.score[self.home.name] - self.score[self.away.name])
        return inning >= self.mercy_min_inning and diff >= self.mercy_margin

    # ------------------------------------------------------------------
    # 스텝 실행 (라이브 중계용)
    # ------------------------------------------------------------------
    def play_next_half(self) -> dict:
        """다음 하프이닝 하나를 통째로(라인업 선발 + 타석 진행) 처리한다.
        라이브 중계에서는 prepare_next_half() / play_prepared_half()로 나눠서 호출한다."""
        if self.finished:
            return {"played": False, "finished": True, "events": [], "result": self.result}
        cursor = len(self.events)
        if self._pending is None:
            self.prepare_next_inning()
        out = self.play_prepared_half()
        out["events"] = self.events[cursor:]   # 라인업 선발 이벤트까지 포함해서 반환
        return out

    def _advance_schedule(self):
        """하프이닝이 끝난 뒤 다음 상태를 결정한다.
        정규이닝 종료 판정을 콜드게임보다 **먼저** 본다 — 그래야 9이닝을 다 치른 경기가
        점수차만 크다는 이유로 '콜드게임'으로 잘못 표시되지 않는다."""
        inning, half = self.current_inning, self.current_half
        if half == "top":
            if inning >= self.max_innings:
                # 마지막 정규이닝: 홈팀이 앞서 있으면 말 공격 불필요, 아니면 반드시 치른다.
                # 점수차가 아무리 커도 홈팀의 마지막 공격 기회를 콜드게임으로 뺏지 않는다
                # (어차피 이닝이 끝나면 경기가 종료되므로 콜드게임을 선언할 실익도 없다)
                if self.score[self.home.name] > self.score[self.away.name]:
                    self._finalize(inning)
                    return
                self.current_half = "bottom"
                return
            if self._check_mercy(inning):
                self._finalize(inning, mercy=True)
                return
            self.current_half = "bottom"
        else:
            if inning >= self.max_innings:
                self._finalize(inning)      # 정규 종료 (점수차가 커도 콜드게임 아님)
                return
            if self._check_mercy(inning):
                self._finalize(inning, mercy=True)
                return
            self.current_inning = inning + 1
            self.current_half = "top"

    def _finalize(self, final_inning: int, mercy: bool = False):
        home_score, away_score = self.score[self.home.name], self.score[self.away.name]
        if home_score > away_score:
            winner = self.home.name
        elif away_score > home_score:
            winner = self.away.name
        else:
            winner = None
        self.mercy_triggered = mercy
        self.final_inning = final_inning
        self.finished = True
        self.result = {
            "home": self.home.name, "away": self.away.name,
            "home_score": home_score, "away_score": away_score,
            "home_hits": self.hits[self.home.name], "away_hits": self.hits[self.away.name],
            "home_errors": self.errors[self.home.name], "away_errors": self.errors[self.away.name],
            "winner": winner, "mercy": mercy, "final_inning": final_inning,
        }
        self._emit({"type": "game_end", **self.result,
                    "text": f"경기 종료{'(콜드게임)' if mercy else ''}: "
                            f"{self.away.name} {away_score} : {home_score} {self.home.name}"})

    # ------------------------------------------------------------------
    # 배치 실행 (CLI/채점용) - 스텝 실행을 끝까지 돌리는 것과 동일
    # ------------------------------------------------------------------
    def run(self) -> dict:
        while not self.finished:
            self.play_next_half()
        return self.result
