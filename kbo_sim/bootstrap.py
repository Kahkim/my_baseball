"""
bootstrap.py
------------
"프로그램 시작하면 데이터를 다운받아 초기 설정하도록 해줘" (구현고려 #5)

데이터는 패키지에 동봉된 kbo_sim/data_snapshot/ 폴더 하나가 유일한 정본(source of truth)이다.
런타임 캐시 폴더 같은 건 따로 두지 않는다 — 헷갈릴 여지를 아예 없애기 위해서다. 실행 시
ensure_data()는 data_snapshot/(또는 명시적으로 넘긴 다른 경로)에 4개 CSV가 있는지 확인하고
바로 load_league_data()로 읽어 메모리에 올린다. 별도의 복사/동기화 단계는 없다.

시즌 데이터를 갱신하고 싶으면 **kbo_sim/data_snapshot/ 안의 CSV 4개(teams.csv, pitchers.csv,
batters.csv, matchup.csv)만 같은 파일명으로 교체**하면 된다. 파일명에는 연도를 넣지 않았다 —
연도가 바뀔 때마다 코드를 고칠 필요 없이 내용만 갈아끼우면 되도록 하기 위해서다.

⚠️ 이 클라우드 개발환경 자체는 KBO 공식 기록실(koreabaseball.com)에 직접적인 네트워크 접근이
막혀 있어(허용목록 프록시), 매 실행마다 실시간으로 사이트를 재수집하는 것은 이 배포판만으로는
불가능하다 (실제로 이 데이터를 최초 수집할 때도 사용자 PC에 연결된 브라우저를 통해 우회 수집함 -
자세한 내용은 프로젝트 문서 `claude/kbo_2025_data_summary.md` 참고). 따라서 "다운로드"는
동봉된 최신 스냅샷을 초기 설정하는 것으로 구현했고, 시즌이 바뀌어 데이터를 갱신하고 싶다면
`refresh_from_kbo_stub()`에 남겨둔 안내를 참고해 별도로 재수집이 필요하다.
"""
from __future__ import annotations

import os

from .data_pipeline import DATA_DIR_DEFAULT, LeagueData, load_league_data

REQUIRED_FILES = ["teams.csv", "pitchers.csv", "batters.csv", "matchup.csv"]
SNAPSHOT_DIR = DATA_DIR_DEFAULT  # kbo_sim/data_snapshot/ — 유일한 데이터 정본 위치


def ensure_data(data_dir: str = DATA_DIR_DEFAULT, verbose: bool = True) -> LeagueData:
    missing = [f for f in REQUIRED_FILES if not os.path.exists(os.path.join(data_dir, f))]
    if missing:
        raise FileNotFoundError(
            f"'{missing}' 데이터가 {data_dir} 에 없습니다. "
            f"kbo_sim/data_snapshot/ 폴더에 teams.csv/pitchers.csv/batters.csv/matchup.csv "
            f"4개가 있는지 확인하거나, claude/kbo_2025_data_summary.md 참고해 재수집이 필요합니다.")
    if verbose:
        print(f"[초기설정] KBO 시즌 데이터 로드 중... ({data_dir})")
    league = load_league_data(data_dir)
    if verbose:
        print(f"[초기설정] 완료 - 팀 {len(league.teams_list())}개, "
              f"타자 {len(league.batter_by_pcode)}명, 투수 {len(league.pitcher_by_pcode)}명, "
              f"맞대결 기록 {len(league.matchup_index)}건")
    return league


def refresh_from_kbo_stub():
    raise NotImplementedError(
        "이 환경에서는 koreabaseball.com에 직접 접근할 수 없습니다. "
        "브라우저가 연결된 환경(예: Claude 데스크톱 앱 연동 세션)에서 "
        "claude/kbo_2025_data_summary.md의 수집 방법을 참고해 CSV를 재생성한 뒤 "
        "kbo_sim/data_snapshot/ 폴더의 teams.csv/pitchers.csv/batters.csv/matchup.csv "
        "4개를 같은 파일명으로 교체해 주세요."
    )
