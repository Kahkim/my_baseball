"""
cli.py
------
"나의 구단주가 되어라" 실행 진입점.

사용 예:
    python -m kbo_sim.cli --a-name 김학생 --a-team 삼성 --a-algo submissions/kim.py \
                           --b-name 이학생 --b-team KT   --b-algo submissions/lee.py \
                           --seed 20260902 --timeout 10 --out output

실행하면:
  1) (구현고려 #5) 데이터 초기 설정
  2) 두 학생 알고리즘 파일을 드랍받아 함수 존재 여부 등 기본 검사 (운영방식 #3,#4)
  3) 3연전(운영방식 #7) 자동 진행, 각 경기 이닝별 학생 알고리즘 실행시간 콘솔 출력
  4) output/game{1,2,3}.json 생성 (viewer/broadcast_viewer.html로 열람)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .bootstrap import ensure_data
from .match import Contestant, Match
from .student_check import full_check


def sanity_check_submission(path: str, label: str, league, team: str, timeout: float) -> bool:
    """제출 코드 검증. 정적 검사(코드를 실행하지 않음) + 격리된 자식 프로세스에서의 1회 호출 테스트.
    ⚠️ 제출 파일을 채점 프로세스에서 그대로 import하면 모듈 최상위 코드(무한루프·파일쓰기 등)가
    아무 보호 없이 실행되므로, 반드시 student_check를 거친다."""
    print(f"[검사] {label} 제출 파일: {path}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} 파일을 찾을 수 없습니다: {path}")
    rep = full_check(path, league, team, None, timeout)
    for e in rep["errors"]:
        print(f"   🚫 {e}")
    for w in rep["warnings"]:
        print(f"   ⚠  {w}")
    for i in rep["infos"]:
        print(f"   ℹ  {i}")
    if rep.get("smoke"):
        for c in rep["smoke"]["cases"]:
            mark = "✓" if c["status"] == "ok" else "✗"
            print(f"   {mark} {c['label']} {c['elapsed_sec']}초"
                  + (f" — {c['detail']}" if c.get("detail") else ""))
    print(f"[검사] {label} {'통과' if rep['ok'] else '실패'}")
    return rep["ok"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="나의 구단주가 되어라 - KBO 메타휴리스틱 시뮬레이션")
    ap.add_argument("--a-name", required=True)
    ap.add_argument("--a-team", required=True, help="예: 삼성, KT, LG, KIA, 두산, NC, 롯데, SSG, 한화, 키움")
    ap.add_argument("--a-algo", required=True, help="학생 A 제출 .py 파일 경로")
    ap.add_argument("--b-name", required=True)
    ap.add_argument("--b-team", required=True)
    ap.add_argument("--b-algo", required=True)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--out", default="output")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    league = ensure_data(args.data_dir) if args.data_dir else ensure_data()

    valid_teams = set(league.teams_list())
    for label, t in (("A", args.a_team), ("B", args.b_team)):
        if t not in valid_teams:
            print(f"오류: 팀 이름 '{t}'을(를) 찾을 수 없습니다. 사용 가능: {sorted(valid_teams)}", file=sys.stderr)
            return 1

    ok_a = sanity_check_submission(args.a_algo, args.a_name, league, args.a_team, args.timeout)
    ok_b = sanity_check_submission(args.b_algo, args.b_name, league, args.b_team, args.timeout)
    if not (ok_a and ok_b):
        print("\n오류: 제출 코드 검증을 통과하지 못했습니다. 위 항목을 고친 뒤 다시 실행하세요.",
              file=sys.stderr)
        return 1

    a = Contestant(args.a_name, args.a_algo, args.a_team)
    b = Contestant(args.b_name, args.b_algo, args.b_team)
    match = Match(league, a, b, seed=args.seed, timeout_sec=args.timeout, output_dir=args.out)

    print(f"\n=== {a.student_name}({a.team_name}) vs {b.student_name}({b.team_name}) 3연전 시작 ===\n")
    mr = match.run_series()

    for g in mr.games:
        r = g.result
        print(f"\n[{g.game_no}경기] {g.away_student}({g.away_team}) {r['away_score']} : "
              f"{r['home_score']} {g.home_student}({g.home_team})"
              f"{'  [콜드게임]' if r['mercy'] else ''} -> JSON: {g.json_path}")

    print(f"\n=== 매치 결과: {mr.score} ===")
    print(f"승자: {mr.winner if mr.winner else '무승부'}\n")

    summary_path = os.path.join(args.out, "match_summary.json")
    os.makedirs(args.out, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"score": mr.score, "winner": mr.winner,
                   "games": [{"game_no": g.game_no, "home_student": g.home_student, "away_student": g.away_student,
                              "home_team": g.home_team, "away_team": g.away_team, "result": g.result,
                              "json_path": g.json_path} for g in mr.games]}, f, ensure_ascii=False, indent=2)
    print(f"요약 저장: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
