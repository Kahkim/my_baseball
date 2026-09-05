"""
match.py
--------
1:1 매치 = 3연전 오케스트레이션 (운영방식 #7).

  1경기: 학생A -> 팀X, 학생B -> 팀Y (학생들이 원래 선택한 그대로)
  2경기: 학생A -> 팀Y, 학생B -> 팀X (서로 팀을 바꿔서). 홈/원정도 1경기와 반대로.
  3경기: 두 팀(X,Y) 중 어느 학생이 어느 팀을 맡을지, 그리고 홈/원정도 전부 무작위로 재배정.

각 경기 결과 승자에게 1점씩 부여, 무승부는 0.5점씩. 3전 합산 점수가 높은 쪽이 매치 승리.

경기 일정(build_series_schedule)은 배치 채점(Match)과 라이브 중계(live_session.SeriesSession)가
**공유**하므로, 같은 시드면 두 모드의 대진/결과가 완전히 동일하다.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .broadcast_export import export_game_to_file
from .data_pipeline import LeagueData
from .game import Game
from .models import build_team


@dataclass
class Contestant:
    student_name: str
    algo_path: str
    team_name: str


@dataclass
class ScheduledGame:
    game_no: int
    home: Contestant
    away: Contestant
    seed: int
    label: str


@dataclass
class MatchGameRecord:
    game_no: int
    home_student: str
    away_student: str
    home_team: str
    away_team: str
    result: dict
    json_path: Optional[str] = None


@dataclass
class MatchResult:
    games: List[MatchGameRecord] = field(default_factory=list)
    score: dict = field(default_factory=dict)  # student_name -> points
    winner: Optional[str] = None


def build_series_schedule(a: Contestant, b: Contestant, master_rng: random.Random) -> List[ScheduledGame]:
    """3연전 대진표 생성. 반드시 master_rng를 순서대로 소비하므로 시드가 같으면 항상 같은 대진."""
    seed1 = master_rng.randrange(2 ** 31)
    g1 = ScheduledGame(1, home=b, away=a, seed=seed1, label="1차전 (선택한 팀 그대로)")

    swapped_a = Contestant(a.student_name, a.algo_path, b.team_name)
    swapped_b = Contestant(b.student_name, b.algo_path, a.team_name)
    seed2 = master_rng.randrange(2 ** 31)
    g2 = ScheduledGame(2, home=swapped_a, away=swapped_b, seed=seed2, label="2차전 (팀 교대)")

    team_pool = [a.team_name, b.team_name]
    master_rng.shuffle(team_pool)
    students = [a, b]
    master_rng.shuffle(students)
    rand_a = Contestant(students[0].student_name, students[0].algo_path, team_pool[0])
    rand_b = Contestant(students[1].student_name, students[1].algo_path, team_pool[1])
    home_away = [rand_a, rand_b]
    master_rng.shuffle(home_away)
    seed3 = master_rng.randrange(2 ** 31)
    g3 = ScheduledGame(3, home=home_away[0], away=home_away[1], seed=seed3, label="3차전 (무작위 배정)")

    return [g1, g2, g3]


def award_points(records: List[MatchGameRecord], name_a: str, name_b: str) -> Tuple[dict, Optional[str]]:
    score = {name_a: 0.0, name_b: 0.0}
    for g in records:
        res = g.result
        if res["winner"] is None:
            score[g.home_student] += 0.5
            score[g.away_student] += 0.5
        else:
            winner_student = g.home_student if res["winner"] == g.home_team else g.away_student
            score[winner_student] += 1.0
    if score[name_a] > score[name_b]:
        winner = name_a
    elif score[name_b] > score[name_a]:
        winner = name_b
    else:
        winner = None
    return score, winner


class Match:
    """배치 실행용 (CLI 채점). 라이브 중계는 live_session.SeriesSession 사용."""

    def __init__(self, league: LeagueData, a: Contestant, b: Contestant, seed: Optional[int] = None,
                 timeout_sec: float = 10.0, output_dir: str = "output", export_json: bool = True):
        self.league = league
        self.a = a
        self.b = b
        self.master_rng = random.Random(seed)
        self.timeout_sec = timeout_sec
        self.output_dir = output_dir
        self.export_json = export_json
        if export_json:
            os.makedirs(output_dir, exist_ok=True)

    def _run_one(self, sched: ScheduledGame) -> MatchGameRecord:
        home_team = build_team(self.league, sched.home.team_name)
        away_team = build_team(self.league, sched.away.team_name)
        algo_path = {home_team.name: sched.home.algo_path, away_team.name: sched.away.algo_path}
        game = Game(self.league, home_team, away_team, algo_path, seed=sched.seed,
                    timeout_sec=self.timeout_sec)
        game.run()
        json_path = None
        if self.export_json:
            json_path = os.path.join(self.output_dir, f"game{sched.game_no}.json")
            algo_meta = {
                home_team.name: {"student_name": sched.home.student_name, "file": sched.home.algo_path},
                away_team.name: {"student_name": sched.away.student_name, "file": sched.away.algo_path},
            }
            export_game_to_file(self.league, game, json_path, algo_meta)
        return MatchGameRecord(game_no=sched.game_no, home_student=sched.home.student_name,
                                away_student=sched.away.student_name, home_team=home_team.name,
                                away_team=away_team.name, result=game.result, json_path=json_path)

    def run_series(self) -> MatchResult:
        mr = MatchResult()
        for sched in build_series_schedule(self.a, self.b, self.master_rng):
            mr.games.append(self._run_one(sched))
        mr.score, mr.winner = award_points(mr.games, self.a.student_name, self.b.student_name)
        return mr
