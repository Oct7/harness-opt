# Class route

Date: 2026-09-18  
Status: draft pending review  
Scope: harness-opt가 지난 작업을 분류하고, 모델/effort 추천 보고서를 남기고, 시작·종료 훅으로 묻고, 목록이 바뀌면 보고서를 다시 돌리자고 한다.  
관련: `2026-09-18-class-calibrate-design.md` (`calibrate`는 그대로. 이 스펙이 훅·보고서·관측 층을 연다.)

## 한 줄

스킬 파일을 고치는 기능(`optimize`)은 그대로 둔다. 새 길은 **Class route**다. 지난 대화를 종류로 나누고, 지금 쓰는 AI가 고를 수 있는 모델 전부 안에서 상한 이하 값을 고르고, 보고서로 남기고, 다음 작업에서 바꿀지 묻고, 끝나면 괜찮았는지 묻는다.

## 안 하는 일

- 대화 모델을 자동으로 바꾸기
- 설정 파일에 모델을 몰래 쓰기
- 달러 맞히기 (current는 계속 `unknown`)
- 에이전트가 목록에 안 준 모델 이름을 만들기
- `optimize` 플래그·테스트 assertion 바꾸기
- 다른 훅 지우기
- TokenMeter나 외부 계량기에 의존
- `--runner cursor`로 `calibrate`/`optimize` 측정 (계속 에러)

## 이미 정한 것

| 항목 | 결정 |
| --- | --- |
| 제품 길 | 스킬 첫 질문: **Skill optimize** 또는 **Class route** |
| 관측 + 검증 | 관측 보고서로 훅을 켠다. `calibrate`가 이긴 유형만 verified로 덮어쓴다 |
| 관측 세션 | 러너 히스토리 **전체** 워크스페이스. `calibrate`는 **지금** 워크스페이스만 |
| 모델 목록 | **지금 이 플러그인을 쓰는 에이전트**가 고를 수 있는 모델 **전부**. 같은 목록 API/디스크 카탈로그. 비면 그 호스트는 건너뛰고 `unverified` |
| 상한 | 지금 디스크(또는 명시) model/effort. 그보다 센 effort 쌍은 버림. 가격으로 모델을 줄이지 않음 |
| 훅 위치 | 플러그인 훅(Claude/Codex/Grok) + Cursor `beforeSubmitPrompt` / 종료 훅. `harness-opt hook install` |
| Cursor 측정 | 없음. Cursor 추천에는 `unverified` |
| 읽기 순서 | 이 워크스페이스 verified override → 클래스 `recommended` → 그 호스트 `observed` → 없으면 침묵 |
| 상태 파일 | `{state-dir}/model-routing/` (기본 `~/.cache/harness-opt`). 레포에 커밋하지 않음 |

## 명령

| 명령 | 하는 일 |
| --- | --- |
| `harness-opt report` | 세션 분류 + 호스트 모델 전부 읽기 + 관측 보고서 + `routing.json`의 `observed` |
| `harness-opt route '<prompt>'` | 훅이 시작 때 호출. 유형, 추천, 물을 문장. JSON |
| `harness-opt feedback --class … --model … --effort … --verdict good\|bad` | 종료 훅이 답을 기록 |
| `harness-opt hook install` | harness-opt 훅만 추가/갱신 |
| `harness-opt catalog --view classes` | 지금과 같음 (워크스페이스 로컬) |
| `harness-opt calibrate` | 지금과 같음. verified만 씀. `observed`는 안 지움 |

`route`와 훅은 추천이 없어도 **exit 0**. 작업을 막지 않는다.

## 스킬 흐름 (Class route)

1. `routing.json`이 오래됐으면 (`catalog_fingerprint`가 지금 목록과 다르거나 `catalog_cutoff`가 30일 지남) **보고서 다시 돌리자**고 먼저 말한다.
2. `report`로 관측 보고서와 `observed`를 쓴다.
3. `hook install`로 시작 훅·종료 훅을 붙인다.
4. 유형을 고르면 기존 `calibrate`로 그 워크스페이스에서 확인한다. 이기면 `recommended`를 덮어쓴다.

`optimize`로 넘어가지 않는다.

## 모델 목록

호출한 에이전트가 목록을 보여주는 **같은 길**로 전부 가져온다.

- Grok: 이미 있는 `grok models` (`native_models`)
- Claude / Codex / Cursor: 각 CLI 또는 그 에이전트가 쓰는 디스크 카탈로그
- 목록에 없는 ID는 후보가 될 수 없다
- 목록이 비면 그 호스트 `observed`는 비우고 보고서에 `unverified`

`calibrate --execution current`도 이 목록을 쓴다. Claude/Codex도 “현재 모델의 낮은 effort만”이 아니다. **목록 전체 × 천장 이하 effort**. Grok와 같은 규칙.

## `routing.json`

한 파일, 두 층. `calibrate`가 지금 쓰는 키는 유지. schema_version 2.

```json
{
  "schema_version": 2,
  "catalog_cutoff": "2026-09-18",
  "catalog_fingerprint": {"cursor": "…", "codex": "…"},
  "classes": {
    "debug_investigate": {
      "observed": {
        "cursor": {"model": "grok-4.6", "effort": "high"},
        "codex": {"model": "gpt-5.6-sol", "effort": "high"}
      },
      "recommended": {"runner": "codex", "model": "gpt-5.6-sol", "effort": "high"},
      "ceiling": {"runner": "codex", "model": "gpt-5.6-sol", "effort": "ultra"},
      "workspace_overrides": {},
      "evidence": [],
      "feedback": []
    }
  }
}
```

- `observed` — `report`만 씀. 호스트 목록 + 상한 이하.
- `recommended` / `ceiling` / `workspace_overrides` / `evidence` — `calibrate`만 씀.
- `feedback` — 종료 훅 답. `report`가 `observed`를 고를 때 읽음.
- `report`는 verified 칸을 안 지운다. `calibrate`는 `observed`·`feedback`을 안 지운다.

## 관측 값이 골라지는 법

모델 호출 없음. 달러 없음.

1. 러너 히스토리 전체를 `classify()`로 센다. 유형별 횟수, 마지막 날짜.
2. 호스트마다 천장 = 디스크의 현재 model/effort.
3. 유형마다 코드에 박힌 effort 상한:  
   git / 원샷 / 트윅 → `low`  
   구현 / 하네스 / 리서치 → `medium`  
   디버그 / 리디자인 / 리뷰 → `high`  
   아키텍처 / 멀티장애 → `xhigh`
4. 그 상한을 천장 effort와 클립한다. 순서는 **그 모델이 에이전트 목록에서 준 effort 배열**.
5. 그 effort를 허용하는 목록 ID가 후보.
6. 천장 모델이 후보면 그걸 고른다. 아니면 목록에서 첫 후보. 없으면 그 호스트 `observed`는 비움.
7. `feedback`이 있으면 덮어쓴다.  
   `good` → 그 쌍을 그 호스트 `observed`로  
   `bad` → 한 칸 위 (천장까지)  
   같은 유형·호스트에 답이 여러 개면 **가장 최근**.

마크다운 보고서는 `{state-dir}/model-routing/REPORT.md`. 유형 표, 천장, `observed`, 어떤 유형이 `calibrate` 가능한지, 최근 피드백. `cases.json`은 `calibrate`만 만든다.

## 시작 훅

이벤트: 플러그인 해당 훅 + Cursor `beforeSubmitPrompt`.  
호출: `harness-opt route`.

입력: 프롬프트, 호스트, 현재 model/effort, 워크스페이스.  
분류: `classify()`. 모델 호출 없음.

물을 때: 지금 값이 추천보다 **높을 때만**. 같거나 낮으면 침묵.

문장 예: `지금 grok-4.6 xhigh. 과거 debug_investigate는 grok-4.6 high. 바꿀까요?`  
Cursor이거나 출처가 `observed`면 `unverified`를 붙인다.

안 함: 모델 변경, 제출 차단, 설정 파일 수정. 사용자가 호스트 UI에서 바꾼다.  
호스트가 권한 프롬프트를 주면 그걸 쓴다. 없으면 메시지를 넘기고 진행.

로그: `{state-dir}/model-routing/outcomes.jsonl` 한 줄 (보여준 추천, 출처, 답이 있으면 수락/거절).

## 종료 훅

이벤트: 그 에이전트의 **작업 끝** 훅 (Cursor `sessionEnd`/`stop`, Claude/Codex 대응 Stop).

한 질문: `이번 작업({유형})에 {model} {effort}. good / bad`

답:

- `good` — 이 종류에 이 값이면 충분
- `bad` — 다음엔 더 셈 (상한까지)

기록만 한다. `feedback`에 append. 다음 `report`가 `observed`에 반영. 지금 대화 모델은 그대로.

안 함: 설문 여러 개, 모델 호출, 종료 막기, 설정 파일 쓰기. 답이 없으면 줄 없음.

분류는 그 세션의 실제 사용자 요청(훅 payload 또는 같은 세션 로그). 잡음 필터는 `classify.py`와 같다. 쓴 모델/effort는 호스트가 훅에 준 값. 둘 중 하나라도 없으면 질문하지 않고 끝낸다.

## 에러

- `route` / 훅: 추천 없음, 분류 실패, 파일 없음 → 침묵, exit 0, JSON 한 장
- `report`: 세션 없음 → 빈 표와 이유, exit 0. 목록 실패 → 그 호스트 `observed` 비움, `unverified`
- 천장 effort가 그 모델 목록에 없으면 그 호스트는 건너뜀
- `hook install`: harness-opt 줄만. 다른 훅 바이트 유지. 파일 없으면 우리 줄만 만들어 생성
- `--runner cursor`: `calibrate`/`optimize`에서 에러
- `git_deploy_ops` / `mixed_or_unclear`: `calibrate` 거부. 보고서와 훅의 `observed`는 git/원샷에도 씀

## 테스트

기존 `optimize` assertion은 수정하지 않는다.

- 호스트 목록 fixture의 모든 ID가 후보에 있고, 목록 밖 ID는 없음
- 천장보다 높은 effort 쌍은 없음
- `route` 추천 없음 → exit 0
- 시작 훅은 현재 ≤ 추천이면 침묵
- 종료 훅 `good`/`bad`가 `feedback`에 남고, 다음 `report`의 `observed`가 그에 맞게 바뀜
- 답 없는 종료는 파일을 안 바꿈
- `hook install`은 다른 훅을 유지
- `report`는 `recommended`/`evidence`를 안 지움
- `calibrate`는 `observed`/`feedback`을 안 지움
- stale이면 `report` 재실행을 제안
- `--runner cursor`는 측정 명령에서 에러

## 파일

- `harness_opt/runner.py` — `native_models()`를 Grok만이 아니라 Claude/Codex/Cursor 목록 전부로 확장. 스킬용 `catalog.py`는 그대로.
- `harness_opt/report.py` — 관측 보고서 + `observed`
- `harness_opt/route.py` — 시작 훅 JSON
- `harness_opt/feedback.py` — 종료 훅 기록
- `harness_opt/hooks.py` + `hooks/` — 설치 스크립트
- `harness_opt/calibrate.py` — current 후보 = 목록 전부 × 천장 이하
- `harness_opt/cli.py`, `skills/harness-opt/SKILL.md`, `references/setup.md`
- `tests/test_report.py`, `test_route.py`, `test_feedback.py`, `test_hooks.py` + `test_calibrate.py` 후보 케이스

새 의존성 없음.

## 클래스 effort 상한 (관측 기본값)

`classify.py`의 유형 이름과 같아야 한다.

| 유형 | 상한 |
| --- | --- |
| `git_deploy_ops`, `content_oneshot`, `ui_tweak` | low |
| `implement_feature`, `harness_plugin`, `research_docs` | medium |
| `debug_investigate`, `ui_redesign`, `review_audit` | high |
| `architecture_greenfield`, `multi_system_incident` | xhigh |
| `mixed_or_unclear` | 훅 침묵, calibrate 거부 |
