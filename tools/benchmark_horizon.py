"""Compare the trusted bundled Horizon strategy against every other example.

Fast mode runs trusted examples in-process; --isolated applies the real five-second
subprocess limit. Reports preserve per-game results and file hashes for reproducibility.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kbo_sim.data_pipeline import load_league_data
from kbo_sim.game import Game
from kbo_sim.models import build_team
from kbo_sim.student_api import DecisionOutcome, load_student_module

PAIRS = [("삼성", "KT"), ("LG", "KIA"), ("두산", "NC"), ("롯데", "SSG"), ("한화", "키움")]
NEW = ROOT / "examples/strategy_horizon.py"
LEAGUE = None


def play(job):
    global LEAGUE
    opponent, pair, seed, new_home, isolated, overrides, candidate_path = job
    candidate_path = Path(candidate_path)
    if LEAGUE is None:
        LEAGUE = load_league_data()
    home, away = PAIRS[pair]
    paths = {home: str(candidate_path if new_home else ROOT / "examples" / opponent),
             away: str(ROOT / "examples" / opponent if new_home else candidate_path)}
    game = Game(LEAGUE, build_team(LEAGUE, home), build_team(LEAGUE, away),
                paths, seed=seed, timeout_sec=5.0)

    def direct(filepath, module_name, *, timeout_sec, **kwargs):
        t0 = time.perf_counter()
        try:
            module = load_student_module(filepath, module_name)
            if Path(filepath) == candidate_path:
                for key, value in overrides.items():
                    if not hasattr(module, key):
                        raise ValueError(f"Candidate has no tunable parameter {key}")
                    setattr(module, key, value)
            result = module.decide_lineup(**kwargs)
        except Exception as exc:
            return DecisionOutcome("error", time.perf_counter() - t0, None, str(exc))
        elapsed = time.perf_counter() - t0
        return DecisionOutcome("ok" if elapsed <= timeout_sec else "timeout", elapsed,
                               result if elapsed <= timeout_sec else None, None)

    if isolated:
        result = game.run()
    else:
        with patch("kbo_sim.game.run_student_decision", direct):
            result = game.run()
    team = home if new_home else away
    rf = result["home_score" if new_home else "away_score"]
    ra = result["away_score" if new_home else "home_score"]
    timings = [t.elapsed_sec for t in game.timings if t.team == team]
    return dict(opponent=opponent, pair=pair, seed=seed, new_home=new_home,
                rf=rf, ra=ra, points=1 if rf > ra else 0.5 if rf == ra else 0,
                timings=timings, fallbacks=sum(t.status != "ok" for t in game.timings if t.team == team),
                opponent_fallbacks=sum(t.status != "ok" for t in game.timings if t.team != team))


def summarize(results):
    summary = {}
    for opponent in sorted({r["opponent"] for r in results}):
        games = [r for r in results if r["opponent"] == opponent]
        times = sorted(t for r in games for t in r["timings"])
        clusters = {}
        for game in games:
            clusters.setdefault((game["pair"], game["seed"]), []).append(game["points"])
        paired = [sum(points) / len(points) for points in clusters.values()]
        rng = random.Random(73019)
        boot = sorted(sum(rng.choices(paired, k=len(paired))) / len(paired) for _ in range(4000))
        summary[opponent] = dict(games=len(games), wins=sum(r["points"] == 1 for r in games),
                                draws=sum(r["points"] == 0.5 for r in games),
                                losses=sum(r["points"] == 0 for r in games),
                                point_rate=sum(r["points"] for r in games) / len(games),
                                point_rate_ci95=[boot[100], boot[3899]],
                                run_diff=sum(r["rf"] - r["ra"] for r in games),
                                max_sec=max(times), p95_sec=times[int(0.95 * (len(times) - 1))],
                                fallbacks=sum(r["fallbacks"] for r in games),
                                opponent_fallbacks=sum(r["opponent_fallbacks"] for r in games))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--seed-start", type=int, default=730000)
    parser.add_argument("--pairs", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--opponents", nargs="*")
    parser.add_argument("--out", default="output/horizon_benchmark.json")
    parser.add_argument("--reserve", type=float, help="Development-only reserve-weight override")
    parser.add_argument("--pitch-model", choices=("sample", "survival", "markov"))
    parser.add_argument("--candidate", default="examples/strategy_horizon.py",
                        help="Trusted local candidate only; fast mode executes it in the parent")
    args = parser.parse_args()
    opponents = sorted(p.name for p in (ROOT / "examples").glob("*.py") if p != NEW)
    if args.opponents:
        unknown = set(args.opponents) - set(opponents)
        if unknown:
            parser.error(f"Unknown bundled examples: {unknown}")
        opponents = args.opponents
    if args.seeds < 1 or args.workers < 1:
        parser.error("seeds and workers must be positive")
    overrides = {}
    if args.reserve is not None:
        overrides["RESERVE_WEIGHT"] = args.reserve
    if args.pitch_model is not None:
        overrides["PITCHER_MODEL"] = args.pitch_model
    if args.isolated and overrides:
        parser.error("Development overrides are only supported in fast mode")
    candidate = (ROOT / args.candidate).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(ROOT):
        parser.error("candidate must be an existing file inside the project")
    jobs = [(o, pair, args.seed_start + pair * 10007 + s * 977, home, args.isolated, overrides, str(candidate))
            for o in opponents for pair in range(args.pairs) for s in range(args.seeds) for home in (True, False)]
    engine_files = ("__init__.py", "game.py", "models.py", "student_api.py", "rng.py",
                    "data_pipeline.py", "fatigue.py", "probability.py", "atbat.py",
                    "defense.py", "traits.py", "pitch_sequence.py")
    files = ([candidate] + [ROOT / "examples" / o for o in opponents]
             + [ROOT / "kbo_sim" / name for name in engine_files]
             + sorted((ROOT / "kbo_sim/data_snapshot").glob("*.csv")))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    results = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, result in enumerate(executor.map(play, jobs), 1):
            results.append(result)
            if index % 10 == 0 or index == len(jobs):
                print(f"{index}/{len(jobs)} games, {time.perf_counter() - started:.1f}s", flush=True)
    changed = [str(p.relative_to(ROOT)) for p in files
               if hashes[str(p.relative_to(ROOT))] != hashlib.sha256(p.read_bytes()).hexdigest()]
    report = dict(config=vars(args), python=sys.version, hashes=hashes,
                  valid=not changed, changed_files=changed, summary=summarize(results), games=results,
                  elapsed_sec=time.perf_counter() - started)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if changed:
        raise RuntimeError(f"Results saved but invalid because files changed: {changed}")
    print(json.dumps(report["summary"], ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
