# 나의 구단주가 되어라

메타휴리스틱(Tabu Search / PSO / GA) 수업용 KBO 야구 시뮬레이션 게임.
2025 KBO 정규시즌 실제 기록(10개 구단, 선수 575명)을 바탕으로, 학생이 제출한 알고리즘이
**매 이닝 출전선수를 결정**하고 그 결과를 네이버 문자중계 스타일로 중계한다.

## 두 가지 실행 방식

### 1) 라이브 중계 (수업 시연용, 권장)

```bash
pip install pandas numpy          # 의존성은 이게 전부
python -m kbo_sim.server          # 브라우저가 자동으로 열림 (http://127.0.0.1:8000)
```

브라우저에서:
1. 두 학생의 **이름 / 구단 선택 / 제출한 .py 파일 드래그&드롭** → 서버가 즉시 코드 검증
   (문법·시그니처, 난수 규칙(`rng`만 사용) 위반, 위험한 호출을 잡아내고, **실제로 한 번 호출해서**
   규칙에 맞는 명단이 제한시간 안에 나오는지까지 확인. 오류가 있으면 시작 버튼이 잠긴다)
2. **[3연전 시작]** → 1차전(선택한 팀) → 2차전(팀 교대) → 3차전(무작위 배정)
3. 진행은 버튼 하나가 역할을 바꿔가며 **이닝당 3번 클릭**:
   - **[다음 라인업 선발 (N회)]** — 이닝 시작에 딱 한 번, 두 학생의 알고리즘이 4번 호출되어
     (두 팀 × 공격·수비) 그 이닝에 쓸 명단이 전부 확정된다. 공수교대 때는 다시 뽑지 않는다.
   - **[다음 공격 진행 (N회초)]** / **[다음 공격 진행 (N회말)]** — 확정된 명단으로 각 하프이닝 진행
   (미리 계산해둔 로그를 재생하는 방식이 아님)
4. **[자동진행]**은 한 경기가 끝나면 자동으로 멈춘다 — 최종 스코어를 확인하고 [다음 경기 시작]을 누른다
5. 화면에 실시간으로 표시되는 것:
   - **그라운드 시각화** — 야구장 위에 수비 9명 배치, 타구 궤적, 처리한 수비수 강조, 주자·타자·아웃카운트
   - 이닝별 스코어보드(R/H/E)와 구단 엠블럼
   - **양 팀 출전명단** (타순 / 수비 포지션 / OPS / 체력 / 포지션 불일치 ⚠)
   - **이닝별·팀별 알고리즘 계산시간** 표
   - 투구 하나하나의 문자중계

미리 팀/파일을 지정해두고 띄우려면:
```bash
python -m kbo_sim.server --a-name 김학생 --a-team 삼성 --a-algo submissions/kim.py \
                          --b-name 이학생 --b-team KT   --b-algo submissions/lee.py --seed 42
```

### 2) 일괄 채점 (여러 조를 자동으로 돌릴 때)

```bash
python -m kbo_sim.cli --a-name 김학생 --a-team 삼성 --a-algo submissions/kim.py \
                       --b-name 이학생 --b-team KT   --b-algo submissions/lee.py \
                       --seed 42 --out output
```
3연전이 즉시 끝까지 진행되고 `output/game1~3.json` + `match_summary.json`이 저장된다.
저장된 JSON은 `viewer/broadcast_viewer.html`(파일 더블클릭)로 열어 리플레이할 수 있다.

> 같은 시드면 라이브 방식과 일괄 채점 방식의 결과가 **완전히 동일**하다 (같은 상태머신·같은 대진표 사용).

## 폴더 구성

```
kbo_sim/                엔진 패키지
kbo_sim/data_snapshot/  KBO 시즌 원천 CSV (teams/pitchers/batters/matchup.csv) — 데이터 정본, 시즌 갱신 시 이 폴더의 CSV만 교체
examples/
  student_algorithm_template.py   학생 제출용 템플릿 (여기서 시작)
  example_ga_lineup.py            GA 예제 — 타순(순열) 최적화 + 스태미너 고려 투수 선택
  example_tabu_lineup.py          Tabu Search 예제 — 수비 10칸 배정 최적화가 주력
  example_pso_lineup.py           PSO 예제 — "가중치 벡터"를 탐색하고 라인업으로 디코딩
  strategy_fatigue_rotation.py    탐색 없이 체력관리 규칙만 지키는 대조군
  strategy_naive_best.py          ⚠️ 잘못된 전략 표본 (에이스 혹사, 체력 무시)
  baseline_random_algorithm.py    무작위 baseline (엔진 테스트용)
viewer/
  live_viewer.html                라이브 중계 화면 (서버가 제공)
  broadcast_viewer.html           저장된 로그 리플레이 (파일로 직접 열기)
  logos/                          공식 구단 로고 이미지를 넣는 곳 (README 참고)
tools/verify.py         엔진 전체 자체점검 — 코드 수정 후 돌려보세요
tools/calibrate.py      득점 환경이 현실적인지 검증하는 밸런스 점검 스크립트
tools/tournament.py     알고리즘 라운드로빈 — "전략에 따라 결과가 달라지는가"를 통계로 확인
docs/                   학생 가이드 / 강사 가이드
output/                 경기 결과 JSON
```

## 모듈 구성 (`kbo_sim/`)

| 파일 | 역할 |
|---|---|
| `data_pipeline.py` | CSV 로드/정제, 리그 평균, 표본축소(shrinkage) 사건확률 계산 |
| `models.py` | Team/PlayerRuntime(경기 중 체력 상태) 등 데이터 구조 |
| `fatigue.py` | 시그모이드 체력저하 모델 |
| `traits.py` | 도루/번트/실책 등 합성 성향 (⚠️ 실제 기록 아님, 명시적으로 문서화) |
| `rng.py` | 학생용/엔진용 RNG 분리 |
| `probability.py` | log5 매치업 확률 + 실제 맞대결 기록 블렌딩 + 체력 반영 |
| `pitch_sequence.py` | 확정된 타석 결과에 맞는 그럴듯한 투구 시퀀스 역생성 |
| `defense.py` | 타구 처리, 포지션 불일치 실책 페널티, 병살/희생플라이 |
| `atbat.py` | 한 타석 전체 처리 (도루/번트/타격 결과/베이스러닝) |
| `student_api.py` | 학생 함수 인터페이스 스펙 + 격리 실행(하드 타임아웃) |
| `student_check.py` | 제출 코드 검증 (AST 정적검사 + 실제 1회 호출 스모크 테스트) |
| `game.py` | 9이닝 경기 엔진 (`prepare_next_inning()` / `play_prepared_half()` / 배치 `run()`), 콜드게임, 이벤트 로그 |
| `match.py` | 3연전 대진표 + 배치 오케스트레이션 |
| `live_session.py` | 3연전 라이브 진행 관리 |
| `server.py` | 라이브 중계 HTTP 서버 (팀선택/파일드랍/이닝진행 API) |
| `broadcast_export.py` | 이벤트 로그 -> 뷰어용 JSON |
| `bootstrap.py` | 최초 실행 시 데이터 초기 설정 |
| `cli.py` | 일괄 채점 진입점 |

자세한 사용법은 `docs/게임_규칙_및_운영_매뉴얼.md`(게임 규칙·실행 방법), `docs/프로그램_매뉴얼.md`
(학생이 구현할 함수 스펙), `docs/강사_가이드.md`(강사)를 참고하세요. `docs/학생_가이드.md`는
학생용 문서로 가는 짧은 안내 페이지입니다.
