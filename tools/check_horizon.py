"""Correctness, reproducibility and real subprocess timing for Horizon."""
import itertools
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.strategy_horizon import _assignment, _transitions, decide_lineup
from kbo_sim.data_pipeline import load_league_data
from kbo_sim.models import GameRosterState, build_team
from kbo_sim.student_api import (team_status_dataframe, matchup_dataframe,
                                run_student_decision, validate_lineups)
from kbo_sim.student_check import static_check


def main():
    rng = random.Random(931)
    for n, m in ((1, 3), (3, 5), (4, 6)):
        for _ in range(20):
            scores = [[rng.uniform(-2, 2) for _ in range(m)] for _ in range(n)]
            result = _assignment(scores)
            actual = sum(scores[i][j] for i, j in enumerate(result))
            optimal = max(sum(scores[i][j] for i, j in enumerate(a))
                          for a in itertools.permutations(range(m), n))
            assert len(set(result)) == n and abs(actual - optimal) < 1e-9
    transitions, rewards = _transitions()
    assert (transitions >= 0).all() and (rewards >= 0).all()
    assert (transitions.sum(axis=2) <= 1 + 1e-12).all()
    assert (abs(transitions[:6].sum(axis=2) - 1) < 1e-12).all()
    for outs in range(3):
        for mask in range(8):
            state = outs * 8 + mask
            assert transitions[5, state, outs * 8] == 1  # home run clears bases
            assert rewards[5, state] == mask.bit_count() + 1
            assert transitions[6, state].sum() == (1 if outs < 2 else 0)
            assert rewards[0, state] == (1 if mask == 7 else 0)
    path = str(ROOT / "examples/strategy_horizon.py")
    static = static_check(path)
    assert static.ok, static.to_dict()
    ld = load_league_data()
    reports = []
    for index, name in enumerate(ld.teams_list()):
        opponent = ld.teams_list()[(index + 1) % len(ld.teams_list())]
        team, opp = build_team(ld, name), build_team(ld, opponent)
        for inning, half, used in ((1, "top", 0), (5, "bottom", 1), (9, "top", 2), (7, "bottom", -1)):
            state = GameRosterState(ld, 88713)
            for p in team.batter_pcodes + team.pitcher_pcodes + opp.batter_pcodes + opp.pitcher_pcodes:
                rt = state.get(p)
                load = rng.uniform(0, 2.5) if used == -1 else used
                rt.swing_count = (rt.swing_target or 12) * load
                rt.pitch_count = (rt.pitch_target or 50) * load
            kwargs = dict(my_team=team_status_dataframe(ld, team, state),
                          opponent_team=team_status_dataframe(ld, opp, state),
                          matchups=matchup_dataframe(ld, [], []),
                          context=dict(inning=inning, half=half, batting_order_start_index=7,
                                       time_budget_sec=5, my_score=3, opponent_score=4,
                                       opp_pitcher_pcode=None))
            first = decide_lineup(**kwargs, rng=random.Random(42))
            second = decide_lineup(**kwargs, rng=random.Random(42))
            assert first == second
            assert not isinstance(validate_lineups(ld, team, first), str)
            # Metadata that leaked current opponent lineups must not affect selection.
            kwargs["context"]["opp_prev_defense"] = list(reversed(opp.batter_pcodes[:9])) + opp.pitcher_pcodes[:1]
            assert first == decide_lineup(**kwargs, rng=random.Random(42))
            result = run_student_decision(path, "horizon_check", **kwargs, rng=random.Random(42), timeout_sec=5)
            assert result.status == "ok", (name, inning, result)
            assert result.lineups == first
            assert result.elapsed < 5
            reports.append(dict(team=name, inning=inning, half=half, elapsed_sec=result.elapsed))
        print(f"{index + 1}/10 teams: legal, deterministic, 5s subprocess checks passed", flush=True)
    out = dict(assignment_oracle_cases=60, static=static.to_dict(), cases=reports,
               max_sec=max(r["elapsed_sec"] for r in reports))
    (ROOT / "output/horizon_checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Maximum subprocess time: {out['max_sec']:.3f}s", flush=True)


if __name__ == "__main__":
    main()
