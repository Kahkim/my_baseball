"""Deterministic regression checks: python tools/test_regressions.py."""
import itertools
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kbo_sim import server
from kbo_sim.atbat import _advance_on_hit
from kbo_sim.data_pipeline import load_league_data
from kbo_sim.game import Game
from kbo_sim.live_session import SeriesSession
from kbo_sim.match import Contestant, Match, MatchGameRecord, award_points, build_series_schedule
from kbo_sim.models import build_team
from kbo_sim.student_api import default_defense_lineup, default_offense_lineup


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.league = load_league_data()
        cls.home = build_team(cls.league, "KT")
        cls.away = build_team(cls.league, "삼성")

    def play_scoring_half(self, hit, inning=9, half="bottom", away_score=0):
        game = Game(self.league, self.home, self.away, {}, seed=42)
        game.current_inning, game.current_half = inning, half
        game.score[self.away.name] = away_score
        batting, fielding = ((self.home, self.away) if half == "bottom"
                              else (self.away, self.home))
        outcomes = iter(["BB", "BB", "BB", hit, "SO", "SO", "SO"])
        def probabilities(*args):
            return {next(outcomes): 1.0}
        with patch("kbo_sim.atbat.resolve_pa_probabilities", probabilities), \
             patch("kbo_sim.atbat.maybe_attempt_steal", return_value=None), \
             patch("kbo_sim.atbat.maybe_attempt_bunt", return_value=False):
            game._play_at_bats(inning, half, batting, fielding,
                               default_defense_lineup(fielding), default_offense_lineup(batting), 0)
        game._advance_schedule()
        return game

    def test_walkoff_hits_score_only_winning_run(self):
        for hit in ("1B", "2B", "3B"):
            with self.subTest(hit=hit):
                game = self.play_scoring_half(hit)
                pa = [e for e in game.events if e["type"] == "pa_result"]
                self.assertEqual(len(pa), 4)
                self.assertEqual(game.result["home_score"], 1)
                self.assertEqual(pa[-1]["runs"], 1)
                self.assertEqual(pa[-1]["rbi"], 1)
                self.assertEqual(pa[-1]["event"], "1B")
                self.assertEqual(sum(p is not None for p in pa[-1]["bases"].values()), 3)
                self.assertEqual(game.events[-2]["runs"], 1)
                self.assertTrue(any(e["type"] == "walkoff" for e in game.events))

    def test_walkoff_from_behind_includes_tying_run(self):
        game = self.play_scoring_half("3B", away_score=1)
        pa = [e for e in game.events if e["type"] == "pa_result"][-1]
        self.assertEqual((game.result["home_score"], game.result["away_score"]), (2, 1))
        self.assertEqual((pa["runs"], pa["rbi"], pa["event"]), (2, 2, "2B"))
        self.assertEqual(sum(p is not None for p in pa["bases"].values()), 2)

    def test_walkoff_homer_keeps_all_runs(self):
        game = self.play_scoring_half("HR")
        pa = [e for e in game.events if e["type"] == "pa_result"][-1]
        self.assertEqual(game.result["home_score"], 4)
        self.assertEqual((pa["runs"], pa["rbi"], pa["event"]), (4, 4, "HR"))
        self.assertFalse(any(pa["bases"].values()))

    def test_non_walkoff_hits_keep_all_runs(self):
        for inning, half in ((8, "bottom"), (9, "top")):
            with self.subTest(inning=inning, half=half):
                game = self.play_scoring_half("3B", inning=inning, half=half)
                pa = [e for e in game.events if e["type"] == "pa_result"]
                self.assertEqual((pa[3]["runs"], pa[3]["rbi"], pa[3]["event"]), (3, 3, "3B"))
                self.assertEqual(len(pa), 7)
                self.assertFalse(any(e["type"] == "walkoff" for e in game.events))

    def test_hit_runner_conservation_for_all_base_states(self):
        for occupied, gain, limit, seed in itertools.product(
                itertools.product((False, True), repeat=3), (1, 2, 3), (None, 1, 2, 3), range(20)):
            bases = {b: (b * 100 if occupied[b - 1] else None) for b in (1, 2, 3)}
            runs, rbi = _advance_on_hit(bases, gain, 999, random.Random(seed), lambda _: 0.5, limit)
            remaining = [p for p in bases.values() if p is not None]
            self.assertEqual(sum(occupied) + 1, runs + len(remaining))
            self.assertEqual(len(remaining), len(set(remaining)))
            self.assertEqual(runs, rbi)
            if limit is not None:
                self.assertLessEqual(runs, limit)

    def test_uploads_preserve_identical_and_sanitized_filenames(self):
        handler = object.__new__(server.Handler)
        responses = []
        handler._json = lambda value, code=200: responses.append(value)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server, "UPLOAD_DIR", tmp), \
             patch.object(server, "APP", SimpleNamespace(league=self.league, timeout_sec=10)), \
             patch.object(server, "full_check", side_effect=lambda *args: {"ok": True}):
            paths = []
            for name, content in (("solution.py", "# A"), ("solution.py", "# B"),
                                  ("a?.py", "# C"), ("a*.py", "# D")):
                handler._api_upload({"filename": name, "content": content})
                paths.append(Path(responses[-1]["result"]["path"]))
            self.assertEqual(len(set(paths)), 4)
            self.assertEqual([p.read_text(encoding="utf-8") for p in paths], ["# A", "# B", "# C", "# D"])
            self.assertEqual(paths[0].name, "solution.py")

    def test_ids_survive_team_and_home_swaps(self):
        a, b = Contestant("동명", "a.py", "KT"), Contestant("동명", "b.py", "삼성")
        for seed in range(30):
            schedule = build_series_schedule(a, b, random.Random(seed))
            records = []
            for sched in schedule:
                for c in (sched.home, sched.away):
                    self.assertEqual(c.algo_path, {"A": "a.py", "B": "b.py"}[c.participant_id])
                winner = next(c.team_name for c in (sched.home, sched.away) if c.participant_id == "A")
                records.append(MatchGameRecord(sched.game_no, "동명", "동명", sched.home.team_name,
                    sched.away.team_name, {"winner": winner},
                    home_id=sched.home.participant_id, away_id=sched.away.participant_id))
            self.assertEqual(award_points(records, "A", "B"), ({"A": 3.0, "B": 0.0}, "A"))
            records[0].result["winner"] = None
            self.assertEqual(award_points(records, "A", "B"), ({"A": 2.5, "B": 0.5}, "A"))
            for record in records:
                record.result["winner"] = None
            self.assertEqual(award_points(records, "A", "B"), ({"A": 1.5, "B": 1.5}, None))

    def test_live_and_batch_keep_separate_same_name_scores(self):
        a, b = Contestant("동명", "a.py", "KT"), Contestant("동명", "b.py", "삼성")
        def finish_for_a(game):
            winning_team = next(t for t, path in game.algo_path.items() if path == "a.py")
            game.score[winning_team] = 1
            game._finalize(9)
            return game.result
        with tempfile.TemporaryDirectory() as tmp:
            session = SeriesSession(self.league, a, b, seed=9, output_dir=tmp)
            for _ in range(3):
                meta = session.start_next_game()
                self.assertEqual({meta["home"]["student_id"], meta["away"]["student_id"]}, {"A", "B"})
                finish_for_a(session.current_game)
                session._record_finished_game()
                session._record_finished_game()  # Retry must not award twice.
            live = session.full_state()["series"]
            with patch.object(Game, "run", finish_for_a):
                batch = Match(self.league, a, b, seed=9, export_json=False).run_series()
            self.assertEqual(live["points"], {"A": 3.0, "B": 0.0})
            self.assertEqual(batch.score, live["points"])
            self.assertEqual(batch.winner, live["series_winner_so_far"])
            self.assertEqual(batch.students, {"A": "동명", "B": "동명"})
            self.assertEqual(live["student_ids"], ["A", "B"])
            self.assertEqual(len(live["records"]), 3)
            self.assertEqual(live["records"][1]["home_id"], "A")
            json.dumps(live, allow_nan=False)

    def test_real_game_batch_and_step_results_match(self):
        def fixed_decision(game, team, opponent, is_offense, *args):
            return default_offense_lineup(team) if is_offense else default_defense_lineup(team)
        # Only lineup selection is fixed; all at-bats, fatigue and game transitions are real.
        with patch.object(Game, "_decide", fixed_decision):
            for seed in (42, 4242, 9000):
                batch = Game(self.league, self.home, self.away, {}, seed=seed)
                step = Game(self.league, self.home, self.away, {}, seed=seed)
                expected = batch.run()
                while not step.finished:
                    step.prepare_next_inning()
                    step.play_prepared_half()
                self.assertEqual(expected, step.result)
                self.assertEqual(batch.events, step.events)

    def test_legacy_distinct_name_records(self):
        r = MatchGameRecord(1, "Alice", "Bob", "KT", "삼성", {"winner": "KT"})
        self.assertEqual(award_points([r], "Alice", "Bob"), ({"Alice": 1.0, "Bob": 0.0}, "Alice"))
        with self.assertRaises(ValueError):
            award_points([], "same", "same")


if __name__ == "__main__":
    unittest.main(verbosity=2)
