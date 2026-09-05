# 나의 구단주가 되어라

**매 이닝 출전선수를 고르는 알고리즘으로 겨루는 KBO 야구 시뮬레이션 과제입니다.**
학생은 Python 함수 `decide_lineup()`을 구현하고, Tabu Search·GA·PSO 등으로 선수 선택과 타순을 탐색합니다.
현재 동봉된 2025 시즌 CSV에는 10개 구단, 타자 294명과 투수 281명(총 575명)이 들어 있습니다.

## 먼저 읽을 문서

| 하고 싶은 일 | 읽을 문서 |
|---|---|
| 설치하고 예제 경기를 실행하기 | 이 README의 빠른 시작 |
| 경기 규칙과 수업 운영 방식 이해하기 | [게임 규칙 및 운영 매뉴얼](docs/게임_규칙_및_운영_매뉴얼.md) |
| 제출 함수 구현하기 | [프로그램 매뉴얼](docs/프로그램_매뉴얼.md) |
| 제출 파일 만들기 | [학생용 템플릿](examples/student_algorithm_template.py)을 복사해 수정 |

## 빠른 시작

아래 명령은 **프로젝트 최상위 폴더**에서 실행합니다. Python 3.12 환경을 기준으로 안내하며,
명령을 한 줄씩 적었으므로 PowerShell과 Anaconda Prompt에서 그대로 사용할 수 있습니다.

### 1. 환경 준비

`my_baseball` conda 환경이 아직 없다면 한 번만 만듭니다.

```shell
conda create -n my_baseball python=3.12 pip -y
```

이미 환경이 있다면 생성 명령을 생략하고 다음을 실행합니다.

```shell
conda activate my_baseball
python -m pip install pandas numpy
```

`conda`를 찾을 수 없다는 오류가 나면 Anaconda Prompt에서 실행하세요.
PowerShell에서도 사용하려면 Anaconda Prompt에서 `conda init powershell`을 실행하고 PowerShell을 새로 엽니다.

### 2. 포함된 예제로 라이브 경기 시작

```shell
python -m kbo_sim.server --a-name 학생A --a-team 삼성 --a-algo examples/student_algorithm_template.py --b-name 학생B --b-team KT --b-algo examples/baseline_random_algorithm.py --seed 42
```

브라우저가 자동으로 열립니다. 열리지 않으면 터미널에 표시된 주소(기본 `http://127.0.0.1:8000`)로 접속하세요.

1. 두 제출 파일의 검사 결과를 확인합니다. 검사는 **공격 1회와 수비 1회**를 실행합니다.
2. **[경기 준비 완료 → 3연전 시작]**을 누릅니다.
3. **[다음 라인업 선발] → [다음 공격 진행(초)] → [다음 공격 진행(말)]** 순서로 진행합니다.
4. 자동진행을 켜면 한 경기가 끝날 때 멈춥니다. 점수를 확인하고 **[다음 경기 시작]**을 누릅니다.

직접 이름·팀·파일을 선택하려면 옵션 없이 `python -m kbo_sim.server`를 실행하세요.
서버 종료는 실행 중인 터미널에서 `Ctrl+C`입니다.

### 3. 내 알고리즘으로 바꾸기

[학생용 템플릿](examples/student_algorithm_template.py)을 `my_algo.py`로 복사하고 함수를 수정합니다.
라이브 화면에 파일을 올리거나, 아래 일괄 실행 명령으로 baseline과 비교하세요.

```shell
python -m kbo_sim.cli --a-name 나 --a-team 삼성 --a-algo my_algo.py --b-name 상대 --b-team KT --b-algo examples/baseline_random_algorithm.py --seed 42 --out output/my_test
```

`my_algo.py`를 먼저 만들어야 합니다. 이 명령은 화면 조작 없이 3경기를 순서대로 실행하므로,
알고리즘 실행시간과 PC 성능에 따라 완료까지 시간이 걸립니다.

## 알고 있어야 할 규칙

- 기본 경기는 9이닝이며 연장전 없이 동점이면 무승부입니다.
- 함수는 이닝 시작에 총 4회(두 학생 각각 수비·공격) 호출됩니다. 공수교대 때 다시 뽑지 않습니다.
- 공격은 타자 9명, 수비는 `[내야수×4, 외야수×3, 포수, DH, 투수]` 순서의 10명을 반환합니다.
- 공격과 수비 명단은 별도로 정합니다. 공격 9명이 수비 명단의 앞 9명과 같아야 한다는 제약은 없습니다.
- 체력은 **한 경기 안에서 회복되지 않으며**, 다음 경기는 새 체력 상태로 시작합니다.
- 기본 제한시간은 함수 호출당 10초입니다. 경기 중 실패한 호출은 직전 유효 명단 또는 기본 명단으로 대체됩니다.
- 3연전은 선택한 팀으로 1경기, 팀과 홈/원정을 바꿔 1경기, 무작위 배정으로 1경기를 치릅니다.

콜드게임·끝내기·타순 이어가기의 자세한 규칙은 [운영 매뉴얼](docs/게임_규칙_및_운영_매뉴얼.md)에 있습니다.

## 결과 보기와 저장

| 실행 방식 | 저장되는 파일 |
|---|---|
| 라이브 서버 | 경기 종료마다 `--out` 폴더에 `game1.json`~`game3.json` |
| 일괄 실행(CLI) | 위 경기 파일과 3연전 요약 `match_summary.json` |

[리플레이 뷰어](viewer/broadcast_viewer.html)를 브라우저로 열고 **`gameN.json` 한 개**를 선택하면 중계를 다시 볼 수 있습니다.
`match_summary.json`은 리플레이용 파일이 아닙니다. 같은 출력 폴더를 다시 사용하면 같은 이름의 결과 파일을 덮어쓰므로,
실험별로 `--out output/test_01`처럼 경로를 나누세요.

같은 데이터·코드·선택 팀·시드로 실행하고, 알고리즘이 전달받은 `rng`만 사용하며 시간 초과 여부도 같다면
라이브와 CLI의 경기 결과를 재현할 수 있습니다. 실행시간 표와 파일 경로까지 같아진다는 뜻은 아닙니다.

## 폴더 안내

| 경로 | 내용 |
|---|---|
| [docs/](docs/) | 학생 배포용 규칙·운영 매뉴얼과 프로그램 매뉴얼 |
| [examples/](examples/) | 제출 템플릿, GA·Tabu·PSO 예제, 비교용 전략 |
| [kbo_sim/](kbo_sim/) | 경기 엔진, 학생 함수 실행·검사, 서버·CLI |
| [kbo_sim/data_snapshot/](kbo_sim/data_snapshot/) | `teams.csv`, `batters.csv`, `pitchers.csv`, `matchup.csv` |
| [viewer/](viewer/) | 라이브 중계 화면과 리플레이 뷰어 |
| [viewer/logos/](viewer/logos/README.md) | 구단 로고 설정 안내 |
| [tools/](tools/) | 회귀 검사, 전체 검사, 밸런스·전략 비교 도구 |
| [uploads/](uploads/) | 라이브에서 올린 제출 파일. 업로드마다 별도 하위 폴더에 저장 |
| [output/](output/) | 기본 경기 결과 저장 폴더 |

실행할 때 동봉된 CSV를 읽으며, KBO 사이트에서 자동으로 최신 데이터를 내려받지는 않습니다.
안타·삼진 등의 확률은 기록에 체력과 보정을 적용한 **모델의 추정값**입니다.
도루 성향과 개인 실책 배수 등은 동봉 CSV에 없는 항목을 보완하는 합성값입니다.

## 개선형 Tabu Search 예제

[example_tabu_advanced.py](examples/example_tabu_advanced.py)는 기존 Tabu 예제에
공격 후보 교체, 상대 투수·맞대결 평가, 수비 체력 보존을 더한 별도 제출 파일입니다.
원래 예제는 비교용으로 유지합니다. 설계와 측정 결과는 [개선형 Tabu 안내](docs/Tabu_개선_예제.md)를 참고하세요.

```shell
python -m kbo_sim.server --a-name 개선Tabu --a-team 삼성 --a-algo examples/example_tabu_advanced.py --b-name 기존Tabu --b-team KT --b-algo examples/example_tabu_lineup.py --seed 42
```

## 개발·운영 점검

최근 수정한 업로드·끝내기·동명이인 집계를 빠르게 검사하려면:

```shell
python tools/test_regressions.py
```

전체 검사는 데이터·타석 처리·학생 코드 실행·경기 반복까지 포함하므로 더 오래 걸립니다.

```shell
python tools/verify.py
```

득점 환경은 `python tools/calibrate.py`, 예제 전략 비교는 `python tools/tournament.py`로 확인할 수 있습니다.
두 도구의 결과는 실행한 조건에서의 측정값이며 특정 전략의 승률이나 실행시간을 보장하지 않습니다.

새로 생성하는 CLI 요약 JSON의 `score`와 `winner`는 참가자 ID `A`/`B`를 사용합니다.
`students`는 ID와 표시 이름의 매핑이고, 경기별 `home_id`/`away_id`는 팀 교대 후에도 같은 참가자를 가리킵니다.
라이브 API의 `points`도 ID를 키로 사용합니다. 기존에 저장된 JSON은 자동 변환하지 않습니다.
