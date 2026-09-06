"""Compare bundled Tabu examples with mirrored team/home assignments.

Default fast mode executes ONLY these trusted examples in-process, freshly importing
on every call. It retains the real game engine and lineup validation but cannot enforce
a hard timeout. --isolated uses the normal subprocess runner. Use --check to also run
real upload smoke checks for all 10 teams and deterministic tired-state validation.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kbo_sim.data_pipeline import load_league_data
from kbo_sim.game import Game
from kbo_sim.models import GameRosterState, build_team
from kbo_sim.student_api import (DecisionOutcome, load_student_module, team_status_dataframe,
    matchup_dataframe, validate_lineups)
from kbo_sim.student_check import full_check

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "examples/example_tabu_lineup.py"
NEW = ROOT / "examples/example_tabu_advanced.py"
PAIRS = [("삼성", "KT"), ("LG", "KIA"), ("두산", "NC"), ("롯데", "SSG"), ("한화", "키움")]


def check_example(ld):
    reports = []
    for name in ld.teams_list():
        opp_name = next(t for t in ld.teams_list() if t != name)
        report = full_check(str(NEW), ld, name, opp_name, 10.0)
        assert report["ok"], report
        assert not report["warnings"], report["warnings"]
        reports.append(report)
        team, opp = build_team(ld, name), build_team(ld, opp_name)
        state = GameRosterState(ld, 19)
        for p in team.batter_pcodes + team.pitcher_pcodes:
            rt = state.get(p)
            rt.swing_count = 30.0
            rt.pitch_count = 100.0
        kwargs = dict(my_team=team_status_dataframe(ld, team, state),
            opponent_team=team_status_dataframe(ld, opp, state), matchups=matchup_dataframe(ld, [], []),
            context={"inning": 9, "half": "bottom", "batting_order_start_index": 7,
                     "opp_pitcher_pcode": opp.pitcher_pcodes[0], "time_budget_sec": 10.0})
        module = load_student_module(str(NEW), "advanced_check")
        first = module.decide_lineup(**kwargs, rng=random.Random(17))
        second = module.decide_lineup(**kwargs, rng=random.Random(17))
        assert first == second, name
        assert not isinstance(validate_lineups(ld, team, first), str), (name, first)
        print(f"CHECK {name}: fresh subprocess + tired deterministic lineups passed", flush=True)
    return reports


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--seed-start", type=int, default=100000)
    ap.add_argument("--pairs", type=int, default=5, choices=range(1, 6))
    ap.add_argument("--isolated", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default="output/tabu_comparison.json")
    args = ap.parse_args()
    if args.seeds < 0:
        ap.error("--seeds must be nonnegative")
    ld = load_league_data()
    checks = check_example(ld) if args.check else []
    results, durations = [], {"advanced": [], "original": []}
    fallbacks = {"advanced": 0, "original": 0}

    def direct(filepath, module_name, *, timeout_sec, **kwargs):
        t0 = time.perf_counter()
        module = load_student_module(filepath, module_name)
        lineups = module.decide_lineup(**kwargs)
        elapsed = time.perf_counter() - t0
        status = "ok" if elapsed <= timeout_sec else "timeout"
        return DecisionOutcome(status, elapsed, lineups if status == "ok" else None,
                               None if status == "ok" else "soft time budget exceeded")

    started = time.perf_counter()
    for pair_no, (home, away) in enumerate(PAIRS[:args.pairs]):
        for index in range(args.seeds):
            seed = args.seed_start + pair_no * 10007 + index * 977
            for advanced_home in (True, False):
                paths = {home: str(NEW if advanced_home else OLD), away: str(OLD if advanced_home else NEW)}
                game = Game(ld, build_team(ld, home), build_team(ld, away), paths, seed=seed)
                if args.isolated:
                    result = game.run()
                else:
                    with patch("kbo_sim.game.run_student_decision", direct):
                        result = game.run()
                advanced_team = home if advanced_home else away
                original_team = away if advanced_home else home
                for timing in game.timings:
                    label = "advanced" if timing.team == advanced_team else "original"
                    durations[label].append(timing.elapsed_sec)
                for event in game.events:
                    if event["type"] == "algo_fallback":
                        fallbacks["advanced" if event["team"] == advanced_team else "original"] += 1
                results.append(dict(seed=seed, home=home, away=away, advanced_home=advanced_home,
                    advanced_runs=game.score[advanced_team], original_runs=game.score[original_team],
                    winner=None if result["winner"] is None else
                           "advanced" if result["winner"] == advanced_team else "original"))
            print(f"{len(results)} games: {home}/{away}, seed={seed}", flush=True)
    wins = sum(r["winner"] == "advanced" for r in results)
    losses = sum(r["winner"] == "original" for r in results)
    draws = len(results) - wins - losses
    summary = dict(lineup_policy="locked_roster_10", mode="isolated" if args.isolated else "trusted in-process (no hard timeout)",
        seeds_per_pair=args.seeds, seed_start=args.seed_start, pairs=PAIRS[:args.pairs],
        games=len(results), wins=wins, draws=draws, losses=losses,
        point_rate=(wins + 0.5 * draws) / len(results) if results else None,
        run_difference=sum(r["advanced_runs"] - r["original_runs"] for r in results),
        fallbacks=fallbacks,
        timing={label: {"calls": len(v), "mean_sec": sum(v)/len(v) if v else None,
                        "max_sec": max(v) if v else None} for label, v in durations.items()},
        elapsed_sec=time.perf_counter() - started, smoke_checks=checks, results=results)
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("results", "smoke_checks")},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
