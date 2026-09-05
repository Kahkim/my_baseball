"""Focused review reproductions; does not modify game source or real uploads."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kbo_sim import server
from kbo_sim.atbat import PAResult
from kbo_sim.data_pipeline import load_league_data
from kbo_sim.game import Game
from kbo_sim.match import MatchGameRecord, award_points
from kbo_sim.models import build_team
from kbo_sim.student_api import default_defense_lineup, default_offense_lineup


def main():
    league = load_league_data()
    home, away = build_team(league, 'KT'), build_team(league, '삼성')
    game = Game(league, home, away, {}, seed=1)
    order = default_offense_lineup(home)
    count = 0

    def scenario(ld, batter, pitcher, defense, rs, rng, bases, outs):
        nonlocal count
        count += 1
        if count <= 3:
            bases[4 - count] = batter
            return PAResult('BB', 'walk', 0, 0, 0, [])
        # Use real hit advancement for a bases-loaded triple in a tied ninth.
        from kbo_sim.atbat import _advance_on_hit
        runs, rbi = _advance_on_hit(bases, 3, batter, rng, lambda _: 0.3)
        return PAResult('3B', 'triple', runs, rbi, 0, [])

    with patch('kbo_sim.game.resolve_plate_appearance', scenario):
        game._play_at_bats(9, 'bottom', home, away,
                           default_defense_lineup(away), order, 0)
    print('walkoff_non_hr_score:', game.score, '(expected home 1, away 0)')

    handler = object.__new__(server.Handler)
    responses = []
    handler._json = lambda value, code=200: responses.append(value)
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(server, 'UPLOAD_DIR', tmp), \
             patch.object(server, 'APP', SimpleNamespace(league=league, timeout_sec=10)), \
             patch.object(server, 'full_check', return_value={'ok': True}):
            handler._api_upload({'filename': 'solution.py', 'content': '# student A'})
            a_path = responses[-1]['result']['path']
            handler._api_upload({'filename': 'solution.py', 'content': '# student B'})
            b_path = responses[-1]['result']['path']
            print('upload_same_path:', a_path == b_path,
                  'student_A_file_now:', Path(a_path).read_text(encoding='utf-8'))

    record = MatchGameRecord(1, 'same', 'same', 'KT', '삼성', {'winner': 'KT'})
    print('same_name_points_and_winner:', award_points([record], 'same', 'same'))


if __name__ == '__main__':
    main()
