# Class route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** harness-opt가 지난 세션을 분류하고, 그 에이전트가 주는 모델 전부 안에서 상한 이하 추천 보고서를 쓰며, 시작·종료 훅으로 묻고, 목록이 바뀌면 보고서를 다시 돌리자고 한다.

**Architecture:** `optimize`는 그대로 둔다. `classify` + 확장된 `native_models()`가 ID 집합이다. `report`가 `observed`를 쓰고, `calibrate`만 `recommended`를 쓴다. `route`/`feedback`은 훅이 호출하는 JSON CLI다. 모델 자동 변경은 없다.

**Tech Stack:** Python 3.11+, stdlib, 기존 `harness_opt` (`unittest`, 새 의존성 없음).

**Spec:** `docs/superpowers/specs/2026-09-18-class-route-design.md`

## Global Constraints

- 대화 모델을 자동으로 바꾸지 않는다. 설정 파일에 모델을 몰래 쓰지 않는다.
- 에이전트 목록에 없는 모델 ID를 만들지 않는다. 달러는 current에서 `unknown`.
- `--runner cursor`는 `calibrate`/`optimize`에서 에러. Cursor 추천은 `unverified`.
- `optimize` 테스트 assertion을 바꾸지 않는다. TokenMeter에 의존하지 않는다.
- 상태 파일은 `{state-dir}/model-routing/` (기본 `~/.cache/harness-opt`). 레포에 커밋하지 않는다.
- `route`와 훅은 추천이 없어도 exit 0. 작업을 막지 않는다.
- 테스트 실행 (repo root): `PYTHONPATH=plugins/harness-opt python3 -m unittest <module> -v`

---

파일 책임:

- `classify.py` — 유형, effort 상한, 전체 히스토리 로드
- `runner.py` — `native_models()`를 호스트 목록 전부로
- `calibrate.py` — 후보 쌍, `write_routing`이 `observed`/`feedback` 유지
- `report.py` — 관측 보고서 + `observed`
- `route.py` — 시작 훅 JSON
- `feedback.py` — 종료 훅 기록
- `hooks.py` + `hooks/*.sh` — 설치
- `cli.py` / `SKILL.md` / `setup.md` — Class route 갈래

---

### Task 1: 유형 effort 상한과 전체 세션 로드

**Files:**
- Modify: `plugins/harness-opt/harness_opt/classify.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: 기존 `CLASSES`, `classify()`, `load_workspace_turns()`
- Produces: `CLASS_EFFORT: dict[str, str]`, `effort_cap(name: str) -> str | None`, `load_turns(runner, days=90, workspace=None) -> tuple[list, dict]`. `workspace`가 있으면 cwd 일치, `None`이면 러너 히스토리 전체. `load_workspace_turns(runner, workspace, days=90)`는 `load_turns(..., workspace=workspace)`를 호출만 한다.

- [ ] **Step 1: Write the failing test**

`tests/test_classify.py`에 추가:

```python
from harness_opt.classify import effort_cap, load_turns, load_workspace_turns

class ClassifyRouteTests(unittest.TestCase):
    def test_effort_caps(self):
        self.assertEqual(effort_cap('git_deploy_ops'), 'low')
        self.assertEqual(effort_cap('content_oneshot'), 'low')
        self.assertEqual(effort_cap('ui_tweak'), 'low')
        self.assertEqual(effort_cap('implement_feature'), 'medium')
        self.assertEqual(effort_cap('harness_plugin'), 'medium')
        self.assertEqual(effort_cap('research_docs'), 'medium')
        self.assertEqual(effort_cap('debug_investigate'), 'high')
        self.assertEqual(effort_cap('ui_redesign'), 'high')
        self.assertEqual(effort_cap('review_audit'), 'high')
        self.assertEqual(effort_cap('architecture_greenfield'), 'xhigh')
        self.assertEqual(effort_cap('multi_system_incident'), 'xhigh')
        self.assertIsNone(effort_cap('mixed_or_unclear'))
        self.assertIsNone(effort_cap('nope'))

    def test_load_turns_all_workspaces(self):
        import json, os, tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest.mock import patch
        stamp = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as temp:
            native = Path(temp) / '.codex'
            sessions = native / 'sessions'
            sessions.mkdir(parents=True)
            other = Path(temp) / 'other'
            mine = Path(temp) / 'mine'
            for cwd, name in ((other, 'a.jsonl'), (mine, 'b.jsonl')):
                (sessions / name).write_text(json.dumps({
                    'type': 'session_meta', 'timestamp': stamp,
                    'payload': {'cwd': str(cwd)},
                }) + '\n' + json.dumps({
                    'type': 'response_item', 'timestamp': stamp,
                    'payload': {'type': 'message', 'role': 'user',
                                'content': [{'type': 'input_text', 'text': '원인?'}]},
                }) + '\n')
            with patch.dict(os.environ, {'CODEX_HOME': str(native)}):
                all_rows, _ = load_turns('codex', days=90, workspace=None)
                one, _ = load_workspace_turns('codex', mine, days=90)
            self.assertEqual(len(all_rows), 2)
            self.assertEqual(len(one), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_classify.ClassifyRouteTests -v`  
Expected: FAIL (`effort_cap` / `load_turns` 없음)

- [ ] **Step 3: Write minimal implementation**

`classify.py`에:

```python
CLASS_EFFORT = {
    'git_deploy_ops': 'low', 'content_oneshot': 'low', 'ui_tweak': 'low',
    'implement_feature': 'medium', 'harness_plugin': 'medium', 'research_docs': 'medium',
    'debug_investigate': 'high', 'ui_redesign': 'high', 'review_audit': 'high',
    'architecture_greenfield': 'xhigh', 'multi_system_incident': 'xhigh',
}

def effort_cap(name):
    return CLASS_EFFORT.get(name)
```

`load_workspace_turns`의 cwd 검사를 `if workspace is not None and (not isinstance(cwd, str) or Path(cwd).resolve() != Path(workspace).resolve()): continue`로 바꾸고, 본문을 `load_turns(runner, days=90, workspace=None)`로 옮긴다. `load_workspace_turns`는 `return load_turns(runner, days, Path(workspace).resolve())`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_classify -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/classify.py tests/test_classify.py
git commit -m "$(cat <<'EOF'
Add class effort caps and all-workspace session load.

EOF
)"
```

---

### Task 2: 호스트 모델 목록 전부

**Files:**
- Modify: `plugins/harness-opt/harness_opt/runner.py` (`native_models`, 새 parse 헬퍼)
- Test: `tests/test_native_models.py`

**Interfaces:**
- Consumes: 기존 `parse_grok_models`, `native_models('grok', profile)`
- Produces: `HOSTS = ('claude', 'codex', 'grok', 'cursor')`, `parse_listed_models(data) -> list[dict]`, `catalog_fingerprint(models) -> str`, `native_models(runner, profile) -> list[dict]`. 각 dict는 `{'id': str, 'provider': 'native', 'efforts': list[str]}`. `profile['catalog']`이 있으면 그걸 쓰고 CLI를 호출하지 않는다. 목록이 비면 `[]`. ID를 지어내지 않는다. `runner=='cursor'`이고 `profile.get('measurement')`이면 `ValueError('--runner cursor')`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_native_models.py`:

```python
import unittest
from harness_opt.runner import catalog_fingerprint, native_models, parse_listed_models

class NativeModelsTests(unittest.TestCase):
    def test_parse_listed_models_keeps_ids_and_efforts(self):
        rows = parse_listed_models([
            {'id': 'grok-4.6', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'composer-2.5-fast', 'efforts': ['low']},
        ])
        self.assertEqual([r['id'] for r in rows], ['grok-4.6', 'composer-2.5-fast'])
        self.assertEqual(rows[0]['efforts'], ['low', 'high', 'xhigh'])

    def test_parse_rejects_empty_and_non_ids(self):
        self.assertEqual(parse_listed_models(['', None, {'name': 'x'}]), [])

    def test_native_models_uses_profile_catalog_for_every_host(self):
        catalog = [{'id': 'a', 'provider': 'native', 'efforts': ['low', 'high']},
                   {'id': 'b', 'provider': 'native', 'efforts': ['high']}]
        for host in ('claude', 'codex', 'grok', 'cursor'):
            self.assertEqual(native_models(host, {'catalog': catalog}), catalog)

    def test_cursor_measurement_is_error(self):
        with self.assertRaisesRegex(ValueError, 'cursor'):
            native_models('cursor', {'measurement': True, 'catalog': [{'id': 'x', 'efforts': ['low']}]})

    def test_empty_catalog_is_empty_list(self):
        self.assertEqual(native_models('claude', {'catalog': []}), [])

    def test_fingerprint_changes_when_ids_change(self):
        a = [{'id': 'a', 'efforts': ['low']}]
        b = [{'id': 'a', 'efforts': ['low']}, {'id': 'b', 'efforts': ['high']}]
        self.assertNotEqual(catalog_fingerprint(a), catalog_fingerprint(b))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_native_models -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`runner.py`에:

```python
import hashlib
HOSTS = ('claude', 'codex', 'grok', 'cursor')

def parse_listed_models(data):
    rows = []
    if not isinstance(data, list):
        return rows
    for item in data:
        if isinstance(item, str) and item.strip():
            rows.append({'id': item.strip(), 'provider': 'native', 'efforts': []})
        elif isinstance(item, dict):
            model_id = item.get('id') or item.get('model')
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            efforts = item.get('efforts') if isinstance(item.get('efforts'), list) else []
            rows.append({'id': model_id.strip(), 'provider': 'native',
                         'efforts': [e for e in efforts if isinstance(e, str) and e]})
    return rows

def catalog_fingerprint(models):
    payload = [(m.get('id'), tuple(m.get('efforts') or [])) for m in models]
    return hashlib.sha256(repr(payload).encode()).hexdigest()
```

`native_models`를 교체한다. `profile.get('catalog')`이 키가 있으면 `parse_listed_models`가 아니라 이미 normalize된 list를 그대로 쓰되, dict면 `parse_listed_models`를 쓴다:

```python
def native_models(runner, profile):
    if runner == 'cursor' and profile.get('measurement'):
        raise ValueError('--runner cursor')
    if runner not in HOSTS:
        raise ValueError('runner must be claude, codex, grok, or cursor')
    if 'catalog' in (profile or {}):
        data = profile['catalog']
        if data and isinstance(data[0], dict) and 'provider' in data[0]:
            return data
        return parse_listed_models(data)
    if runner == 'grok':
        # keep the existing grok models CLI body
        ...
    return _disk_or_cli_models(runner, profile)
```

`_disk_or_cli_models`:

1. `shutil.which(runner)`가 있고 `runner != 'cursor'`이면 `[binary, 'models']`를 timeout 30으로 실행. stdout이 있으면 Grok 형식(`parse_grok_models`) 또는 JSON list/`{"models":[...]}`를 `parse_listed_models`로 읽는다. returncode != 0이면 디스크만.
2. 디스크: Claude는 `_native_config_root('claude') / 'settings.json'`의 `availableModels` 또는 `models`(list일 때만). Codex는 `config.toml`의 `models`가 list이거나 각 항목이 `id`를 가진 list일 때만. Cursor는 `Path.home() / '.cursor' / 'cli-config.json'`의 `availableModels` 또는 `models`(list일 때만). 키가 없거나 문자열이 한 개뿐이면 **현재 모델 하나만 목록으로 쓰지 않는다** — 명시적 list만. 없으면 `[]`.

Grok 기존 CLI 경로는 유지한다. 새 호스트에서 CLI가 실패하면 예외를 삼키고 `[]`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_native_models tests.test_current -v`  
Expected: PASS (`test_current`의 grok `native_models` 동작 유지)

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/runner.py tests/test_native_models.py
git commit -m "$(cat <<'EOF'
List every host-catalog model id without inventing names.

EOF
)"
```

---

### Task 3: current 후보 = 목록 전부 × 천장 이하

**Files:**
- Modify: `plugins/harness-opt/harness_opt/calibrate.py` (`candidate_pairs`, `write_routing`, `read_routing`)
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `native_models()`, `_below_ceiling()`
- Produces: `candidate_pairs(...)`가 grok 분기를 없애고, current에서 `native_models(runner, profile)`의 모든 ID × `_below_ceiling(efforts, ceiling_effort)`를 쓴다. 천장 쌍은 제외. 후보가 없으면 기존처럼 `ValueError('no candidate below ceiling; use --execution api')`. `write_routing`은 기존 `observed`/`feedback`을 지우지 않고 `schema_version`을 최소 2로 둔다.

- [ ] **Step 1: Write the failing test**

`tests/test_calibrate.py`의 `CandidatePairTests`에:

```python
    def test_current_uses_full_catalog_below_ceiling(self):
        catalog = [
            {'id': 'ceiling', 'provider': 'native', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'other', 'provider': 'native', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'skip', 'provider': 'native', 'efforts': ['xhigh']},
        ]
        profile = {'effort': 'high', 'model': 'ceiling', 'catalog': catalog}
        with patch('harness_opt.calibrate.native_models', return_value=catalog):
            pairs = candidate_pairs('claude', 'current', profile, [], 'ceiling', 'high')
        self.assertEqual(sorted((m['id'], effort) for m, effort in pairs),
                         [('ceiling', 'low'), ('other', 'high'), ('other', 'low')])
```

`RoutingTests`에:

```python
    def test_write_routing_keeps_observed_and_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            path = state / 'model-routing' / 'routing.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 2, "classes": {"debug_investigate": {'
                            '"observed": {"cursor": {"model": "grok-4.6", "effort": "high"}},'
                            '"feedback": [{"verdict": "ok"}], "evidence": []}}}')
            write_routing(state, 'debug_investigate', '/ws',
                          {'runner': 'codex', 'model': 'a', 'effort': 'low'},
                          {'runner': 'codex', 'model': 'a', 'effort': 'high'},
                          {'winner': {'runner': 'codex', 'model': 'a', 'effort': 'low'},
                           'improvements': ['completion_time'], 'mean_duration': 1})
            data = json.loads(path.read_text())
            row = data['classes']['debug_investigate']
            self.assertEqual(row['observed']['cursor']['model'], 'grok-4.6')
            self.assertEqual(row['feedback'][0]['verdict'], 'ok')
            self.assertGreaterEqual(data['schema_version'], 2)
```

기존 `test_grok_current_uses_captured_effort_only`는 assertion을 바꾸지 않는다. 구현이 그 결과를 그대로 내야 한다 (천장 effort만, 천장 모델 제외).

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_calibrate.CandidatePairTests.test_current_uses_full_catalog_below_ceiling tests.test_calibrate.RoutingTests.test_write_routing_keeps_observed_and_feedback -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`candidate_pairs`의 current 분기를:

```python
    if execution == 'current':
        listed = native_models(runner, dict(profile, measurement=(runner == 'cursor')))
        pairs = []
        for model in listed:
            allowed = _below_ceiling(model.get('efforts') or [], ceiling_effort)
            for item in allowed:
                if model.get('id') == ceiling_model and item == ceiling_effort:
                    continue
                pairs.append((model, item))
        if not pairs:
            raise ValueError('no candidate below ceiling; use --execution api')
        return pairs
```

`write_routing`에서 setdefault에 `'observed': {}, 'feedback': []`를 넣고, 이미 있으면 덮어쓰지 않는다. 파일 루트 `schema_version`은 `max(int(data.get('schema_version') or 1), 2)`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_calibrate -v`  
Expected: PASS (기존 assertion 포함)

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/calibrate.py tests/test_calibrate.py
git commit -m "$(cat <<'EOF'
Compare every listed model below the captured ceiling.

EOF
)"
```

---

### Task 4: `observed` 고르기

**Files:**
- Create: `plugins/harness-opt/harness_opt/report.py` (`pick_observed`만 먼저)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `effort_cap()`, `_below_ceiling()` (calibrate에서 import 또는 report에 같은 5줄 복제하지 말고 `from .calibrate import _below_ceiling`)
- Produces: `pick_observed(task_class, models, ceiling_model, ceiling_effort, feedback=None) -> dict | None`  
  `{'model': str, 'effort': str}` 또는 `None`.  
  `feedback`는 `{model, effort, verdict}` 최신 한 개. `ok`면 그 쌍(목록·천장 안일 때만). `weak`는 effort를 목록에서 한 칸 위(천장까지). `strong`은 한 칸 아래. 목록/천장 밖이면 `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report.py`:

```python
import unittest
from harness_opt.report import pick_observed

MODELS = [
    {'id': 'grok-4.6', 'efforts': ['low', 'medium', 'high', 'xhigh']},
    {'id': 'composer-2.5-fast', 'efforts': ['low', 'medium']},
]

class PickObservedTests(unittest.TestCase):
    def test_debug_picks_ceiling_model_at_class_cap(self):
        self.assertEqual(
            pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh'),
            {'model': 'grok-4.6', 'effort': 'high'})

    def test_git_is_low_on_ceiling_model_if_allowed(self):
        self.assertEqual(
            pick_observed('git_deploy_ops', MODELS, 'grok-4.6', 'xhigh'),
            {'model': 'grok-4.6', 'effort': 'low'})

    def test_falls_back_to_first_model_that_allows_effort(self):
        only = [{'id': 'composer-2.5-fast', 'efforts': ['low']}]
        self.assertEqual(
            pick_observed('git_deploy_ops', only, 'missing', 'low'),
            {'model': 'composer-2.5-fast', 'effort': 'low'})

    def test_mixed_and_unknown_are_none(self):
        self.assertIsNone(pick_observed('mixed_or_unclear', MODELS, 'grok-4.6', 'xhigh'))

    def test_above_ceiling_effort_not_used(self):
        self.assertEqual(
            pick_observed('architecture_greenfield', MODELS, 'grok-4.6', 'high'),
            {'model': 'grok-4.6', 'effort': 'high'})

    def test_feedback_ok_weak_strong(self):
        ok = {'model': 'grok-4.6', 'effort': 'medium', 'verdict': 'ok'}
        self.assertEqual(pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh', ok),
                         {'model': 'grok-4.6', 'effort': 'medium'})
        weak = {'model': 'grok-4.6', 'effort': 'medium', 'verdict': 'weak'}
        self.assertEqual(pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh', weak),
                         {'model': 'grok-4.6', 'effort': 'high'})
        strong = {'model': 'grok-4.6', 'effort': 'high', 'verdict': 'strong'}
        self.assertEqual(pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh', strong),
                         {'model': 'grok-4.6', 'effort': 'medium'})

    def test_unknown_id_not_invented(self):
        self.assertIsNone(pick_observed('debug_investigate', MODELS, 'nope', 'high'))
```

마지막 테스트: 천장 모델이 목록에 없고 다른 모델이 `high`를 허용하면 목록 첫 후보가 된다. `nope`/`high`이고 composer는 high가 없으므로 debug(high)는 `{'model': 'grok-4.6', 'effort': 'high'}`. “unknown id not invented”는 목록이 composer-only일 때 high를 못 내면 None:

```python
    def test_unknown_id_not_invented(self):
        only = [{'id': 'composer-2.5-fast', 'efforts': ['low']}]
        self.assertIsNone(pick_observed('debug_investigate', only, 'nope', 'high'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_report -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `plugins/harness-opt/harness_opt/report.py`:

```python
from .calibrate import _below_ceiling
from .classify import effort_cap

def _shift(listed, effort, step):
    if effort not in listed:
        return None
    index = listed.index(effort) + step
    if 0 <= index < len(listed):
        return listed[index]
    return listed[0] if step < 0 else listed[-1]

def pick_observed(task_class, models, ceiling_model, ceiling_effort, feedback=None):
    cap = effort_cap(task_class)
    if not cap or not models:
        return None
    by_id = {m['id']: m.get('efforts') or [] for m in models if m.get('id')}
    def clip(model_id, wanted):
        listed = by_id.get(model_id) or []
        allowed = _below_ceiling(listed, ceiling_effort)
        if wanted in allowed:
            return wanted
        if not allowed:
            return None
        return allowed[-1] if listed.index(allowed[-1]) <= listed.index(wanted) if wanted in listed else True else allowed[-1]
```

클립은 단순화한다: `wanted`가 `allowed`에 있으면 그걸, 없으면 `allowed`의 마지막(천장 쪽).

```python
    def clip(model_id, wanted):
        listed = by_id.get(model_id) or []
        allowed = _below_ceiling(listed, ceiling_effort)
        if not allowed:
            return None
        if wanted in allowed:
            return wanted
        return allowed[-1]

    if isinstance(feedback, dict) and feedback.get('verdict') in ('ok', 'weak', 'strong'):
        model_id = feedback.get('model')
        effort = feedback.get('effort')
        listed = by_id.get(model_id) or []
        if model_id in by_id and effort in listed:
            if feedback['verdict'] == 'weak':
                effort = _shift(listed, effort, 1)
            elif feedback['verdict'] == 'strong':
                effort = _shift(listed, effort, -1)
            effort = clip(model_id, effort)
            if effort:
                return {'model': model_id, 'effort': effort}

    wanted = cap
    if ceiling_model in by_id:
        effort = clip(ceiling_model, wanted)
        if effort:
            return {'model': ceiling_model, 'effort': effort}
    for model in models:
        effort = clip(model['id'], wanted)
        if effort:
            return {'model': model['id'], 'effort': effort}
    return None
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_report -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/report.py tests/test_report.py
git commit -m "$(cat <<'EOF'
Pick observed model/effort from the host catalog and class cap.

EOF
)"
```

---

### Task 5: `report`가 파일에 쓰기

**Files:**
- Modify: `plugins/harness-opt/harness_opt/report.py`, `plugins/harness-opt/harness_opt/cli.py`
- Test: `tests/test_report.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_turns`, `class_summary`, `pick_observed`, `read_routing`, `native_models`, `catalog_fingerprint`
- Produces: `write_report(state_dir, hosts, coverage, stale=False) -> dict`  
  `report(runner, state_dir, days=90, hosts=None, catalogs=None, ceilings=None) -> dict`  
  `hosts` 기본 `('claude', 'codex', 'grok', 'cursor')`. `catalogs`/`ceilings`는 `{host: ...}` 테스트 주입.  
  반환: `{path, markdown_path, classes, stale, catalog_fingerprint}`.  
  `observed`만 갱신. `recommended`/`evidence`/`feedback` 유지.  
  CLI: `harness-opt report --runner claude`는 그 러너 세션 + 그 호스트 목록. 세션이 없으면 빈 표, exit 0.

- [ ] **Step 1: Write the failing test**

```python
import json, tempfile
from pathlib import Path
from harness_opt.report import report as write_class_report

class WriteReportTests(unittest.TestCase):
    def test_writes_observed_and_keeps_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            routing = state / 'model-routing' / 'routing.json'
            routing.parent.mkdir(parents=True)
            routing.write_text(json.dumps({
                'schema_version': 2,
                'classes': {'debug_investigate': {
                    'recommended': {'runner': 'codex', 'model': 'sol', 'effort': 'high'},
                    'evidence': [{'run_id': 'x'}],
                    'feedback': [{'verdict': 'ok', 'model': 'grok-4.6', 'effort': 'high', 'host': 'cursor'}],
                    'observed': {},
                }},
            }))
            rows = [dict(prompt='로그인 오류 원인 파악', stamp='2026-09-18T00:00:00+00:00',
                         later=[], session='s1', failed=False)]
            result = write_class_report(
                'cursor', state, hosts=('cursor',),
                catalogs={'cursor': [{'id': 'grok-4.6', 'efforts': ['low', 'high', 'xhigh']}]},
                ceilings={'cursor': {'model': 'grok-4.6', 'effort': 'xhigh'}},
                turns=rows)
            data = json.loads(routing.read_text())
            row = data['classes']['debug_investigate']
            self.assertEqual(row['recommended']['model'], 'sol')
            self.assertEqual(row['evidence'][0]['run_id'], 'x')
            self.assertEqual(row['observed']['cursor']['effort'], 'high')
            self.assertTrue((state / 'model-routing' / 'REPORT.md').is_file())
            self.assertEqual(result['status'], 'ok')

    def test_empty_history_is_ok(self):
        with tempfile.TemporaryDirectory() as temp:
            result = write_class_report(
                'codex', Path(temp), hosts=('codex',),
                catalogs={'codex': []}, ceilings={'codex': {'model': 'x', 'effort': 'high'}},
                turns=[])
            self.assertEqual(result['status'], 'ok')
            self.assertIn('empty', result.get('reason', 'empty'))
```

`cli.py`에 `report` 서브커맨드가 없으면 다음 테스트가 실패한다:

```python
    def test_report_command_exists(self):
        args = parser().parse_args(['report', '--runner', 'codex'])
        self.assertEqual(args.command, 'report')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_report.WriteReportTests tests.test_cli.CliTests.test_report_command_exists -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`report()` 시그니처에 `turns=None`을 두어 테스트가 세션 스캔을 건너뛰게 한다. 본문:

1. `data = read_routing(state_dir)` 후 `schema_version = max(...)`.
2. `turns = turns if turns is not None else load_turns(runner if runner != 'cursor' else 'claude', days)` — Cursor 세션 포맷이 없으면 이 함수는 `turns` 주입만 받고, live Cursor 스캔은 하지 않는다 (목록·훅만 Cursor). live `runner=='cursor'`이면 세션 로드를 건너뛰고 `turns=[]`로 두되, `catalogs`가 있으면 유형 표는 기존 `data['classes']` 키 + `CLASS_EFFORT`로 채운다.  
   더 단순: `runner=='cursor'` live는 `load_turns`를 호출하지 않는다. 유형은 `CLASS_EFFORT` 키 전부. count는 0. 테스트는 `turns=`를 넘긴다.
3. `class_summary(turns)`로 count. turns가 비고 테스트가 rows를 주면 그걸 쓴다.
4. 호스트마다 `native_models(host, {'catalog': catalogs[host]})` if catalogs else `native_models(host, ceilings[host] or {})`.
5. 유형마다 그 호스트 `feedback` 중 가장 최근(`stamp` 있으면 그걸로, 없으면 리스트 마지막)을 `pick_observed`에 넘긴다.
6. `row.setdefault('observed', {})[host] = picked` 또는 키가 있으면 삭제하지 말고, picked가 None이면 그 호스트 키를 pop.
7. `_atomic_text`로 routing + REPORT.md (유형, count, observed, recommended 있는지, stale 여부).
8. CLI `report`는 `state_dir` 기본 `Path.home() / '.cache' / 'harness-opt'`.

`stale`은 Task 8에서 채운다. 지금은 `stale=False`를 넣기만 한다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_report tests.test_cli -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/report.py plugins/harness-opt/harness_opt/cli.py tests/test_report.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
Write observational routing report without dropping verified rows.

EOF
)"
```

---

### Task 6: `route`

**Files:**
- Create: `plugins/harness-opt/harness_opt/route.py`
- Modify: `plugins/harness-opt/harness_opt/cli.py`
- Test: `tests/test_route.py`

**Interfaces:**
- Consumes: `classify()`, `read_routing()`, `effort_cap()`
- Produces: `route(prompt, host, current_model, current_effort, workspace, state_dir) -> dict`  
  항상 키: `ask` (bool), `message` (str, 침묵이면 `''`), `class`, `source` (`override`|`recommended`|`observed`|`none`), `recommended` (`{model, effort}`|None), `unverified` (bool).  
  읽기: workspace override → `recommended` (host가 recommended.runner와 같거나, host가 cursor면 recommended를 쓰되 unverified) → `observed[host]`.  
  `mixed_or_unclear`이거나 추천 없으면 `ask=False`.  
  물을 때: 현재 model/effort가 추천보다 높을 때만 (`_rank(current) > _rank(recommended)`). 같은 모델에서 effort 배열 인덱스. 다른 모델이면 현재가 천장이면 묻는다(effort 인덱스만 비교 가능하면 그걸로, 아니면 현재 effort가 추천 effort보다 목록에서 뒤일 때).  
  메시지: `지금 {model} {effort}. 과거 {class}는 {rec_model} {rec_effort}. 바꿀까요?` + (`unverified`이면 ` unverified`).  
  `outcomes.jsonl`은 `ask=True`일 때만 append.

- [ ] **Step 1: Write the failing test**

Create `tests/test_route.py`:

```python
import json, tempfile
from pathlib import Path
import unittest
from harness_opt.route import route

class RouteTests(unittest.TestCase):
    def fixture(self, row):
        state = Path(tempfile.mkdtemp())
        path = state / 'model-routing' / 'routing.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema_version': 2, 'classes': {'debug_investigate': row}}))
        return state

    def test_asks_when_current_above_observed(self):
        state = self.fixture({'observed': {'cursor': {'model': 'grok-4.6', 'effort': 'high'}}})
        result = route('로그인 오류 원인', 'cursor', 'grok-4.6', 'xhigh', '/ws', state)
        self.assertTrue(result['ask'])
        self.assertIn('바꿀까요?', result['message'])
        self.assertIn('unverified', result['message'])
        self.assertEqual(result['source'], 'observed')
        self.assertTrue((state / 'model-routing' / 'outcomes.jsonl').is_file())

    def test_silence_when_at_or_below(self):
        state = self.fixture({'observed': {'cursor': {'model': 'grok-4.6', 'effort': 'high'}}})
        result = route('로그인 오류 원인', 'cursor', 'grok-4.6', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['message'], '')

    def test_prefers_workspace_override(self):
        state = self.fixture({
            'observed': {'codex': {'model': 'sol', 'effort': 'high'}},
            'recommended': {'runner': 'codex', 'model': 'sol', 'effort': 'high'},
            'workspace_overrides': {'/ws': {'runner': 'codex', 'model': 'luna', 'effort': 'low'}},
        })
        result = route('로그인 오류 원인', 'codex', 'sol', 'ultra', '/ws', state)
        self.assertEqual(result['recommended']['model'], 'luna')
        self.assertEqual(result['source'], 'override')

    def test_mixed_is_silent(self):
        state = self.fixture({})
        result = route('asdf', 'codex', 'sol', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['source'], 'none')

    def test_missing_routing_is_silent_exit_shape(self):
        state = Path(tempfile.mkdtemp())
        result = route('로그인 오류 원인', 'codex', 'sol', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['source'], 'none')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_route -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`route.py`:

```python
import json, os
from pathlib import Path
from .calibrate import read_routing
from .classify import classify
from .optimizer import _atomic_text

ORDER = ('low', 'medium', 'high', 'xhigh', 'ultra', 'max')

def _rank(effort):
    return ORDER.index(effort) if effort in ORDER else -1

def _pick(row, host, workspace):
    overrides = row.get('workspace_overrides') or {}
    key = str(Path(workspace).resolve()) if workspace else ''
    if key in overrides:
        return overrides[key], 'override', host == 'cursor'
    rec = row.get('recommended')
    if isinstance(rec, dict) and rec.get('model'):
        return rec, 'recommended', host == 'cursor' or rec.get('runner') != host
    observed = (row.get('observed') or {}).get(host)
    if isinstance(observed, dict) and observed.get('model'):
        return observed, 'observed', True
    return None, 'none', True

def route(prompt, host, current_model, current_effort, workspace, state_dir):
    task_class = classify(prompt)
    empty = {'ask': False, 'message': '', 'class': task_class, 'source': 'none',
             'recommended': None, 'unverified': True}
    if task_class == 'mixed_or_unclear':
        return empty
    data = read_routing(state_dir)
    row = (data.get('classes') or {}).get(task_class) or {}
    picked, source, unverified = _pick(row, host, workspace)
    if not picked:
        return empty
    rec_effort = picked.get('effort')
    ask = _rank(current_effort) > _rank(rec_effort)
    if not ask:
        return dict(empty, class=task_class, source=source, recommended=picked, unverified=unverified)
    message = f"지금 {current_model} {current_effort}. 과거 {task_class}는 {picked.get('model')} {rec_effort}. 바꿀까요?"
    if unverified:
        message += ' unverified'
    result = {'ask': True, 'message': message, 'class': task_class, 'source': source,
              'recommended': {'model': picked.get('model'), 'effort': rec_effort},
              'unverified': unverified}
    path = Path(state_dir) / 'model-routing' / 'outcomes.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + '\n')
    os.chmod(path, 0o600)
    return result
```

CLI: `route` 위치 인자 `prompt`, `--host`, `--model`, `--effort`, `--workspace`, `--state-dir`. 출력 JSON. 항상 return 0.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_route tests.test_cli -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/route.py plugins/harness-opt/harness_opt/cli.py tests/test_route.py
git commit -m "$(cat <<'EOF'
Ask to drop model/effort only when the current pair is above the recommendation.

EOF
)"
```

---

### Task 7: `feedback`

**Files:**
- Create: `plugins/harness-opt/harness_opt/feedback.py`
- Modify: `plugins/harness-opt/harness_opt/cli.py`
- Test: `tests/test_feedback.py`

**Interfaces:**
- Consumes: `read_routing`, `_atomic_text`, `CLASSES`
- Produces: `record_feedback(state_dir, task_class, host, model, effort, verdict) -> dict`  
  `verdict` in `ok|weak|strong`. 그 외·빠진 model/effort/class → `{'status': 'skipped'}` 파일 불변.  
  append `{host, model, effort, verdict, stamp}` to `classes[task_class].feedback`. `observed`/`recommended`는 여기서 안 바꿈.

- [ ] **Step 1: Write the failing test**

Create `tests/test_feedback.py`:

```python
import json, tempfile
from pathlib import Path
import unittest
from harness_opt.feedback import record_feedback
from harness_opt.report import pick_observed

class FeedbackTests(unittest.TestCase):
    def test_appends_and_skips_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            before = record_feedback(state, 'debug_investigate', 'cursor', 'grok-4.6', 'high', 'ok')
            self.assertEqual(before['status'], 'ok')
            data = json.loads((state / 'model-routing' / 'routing.json').read_text())
            self.assertEqual(data['classes']['debug_investigate']['feedback'][-1]['verdict'], 'ok')
            raw = (state / 'model-routing' / 'routing.json').read_bytes()
            skipped = record_feedback(state, 'debug_investigate', 'cursor', '', 'high', 'ok')
            self.assertEqual(skipped['status'], 'skipped')
            self.assertEqual((state / 'model-routing' / 'routing.json').read_bytes(), raw)

    def test_latest_feedback_changes_next_observed(self):
        models = [{'id': 'grok-4.6', 'efforts': ['low', 'medium', 'high', 'xhigh']}]
        self.assertEqual(
            pick_observed('debug_investigate', models, 'grok-4.6', 'xhigh',
                          {'model': 'grok-4.6', 'effort': 'high', 'verdict': 'strong'}),
            {'model': 'grok-4.6', 'effort': 'medium'})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_feedback -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
from datetime import datetime, timezone
from pathlib import Path
from .calibrate import read_routing, routing_path
from .classify import CLASSES
from .optimizer import _atomic_text
import json, os

def record_feedback(state_dir, task_class, host, model, effort, verdict):
    if task_class not in CLASSES or task_class == 'mixed_or_unclear':
        return {'status': 'skipped'}
    if verdict not in ('ok', 'weak', 'strong') or not model or not effort or not host:
        return {'status': 'skipped'}
    data = read_routing(state_dir)
    data['schema_version'] = max(int(data.get('schema_version') or 1), 2)
    row = data.setdefault('classes', {}).setdefault(task_class, {
        'observed': {}, 'recommended': None, 'ceiling': None,
        'workspace_overrides': {}, 'evidence': [], 'feedback': []})
    row.setdefault('feedback', []).append({
        'host': host, 'model': model, 'effort': effort, 'verdict': verdict,
        'stamp': datetime.now(timezone.utc).isoformat()})
    path = routing_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(path, 0o600)
    return {'status': 'ok'}
```

CLI: `feedback --class --host --model --effort --verdict`. skip이어도 exit 0.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_feedback -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/feedback.py plugins/harness-opt/harness_opt/cli.py tests/test_feedback.py
git commit -m "$(cat <<'EOF'
Record end-of-work model feedback without changing the live session.

EOF
)"
```

---

### Task 8: stale + `hook install`

**Files:**
- Create: `plugins/harness-opt/harness_opt/hooks.py`
- Create: `plugins/harness-opt/hooks/cursor-start.sh`
- Create: `plugins/harness-opt/hooks/cursor-end.sh`
- Modify: `plugins/harness-opt/harness_opt/report.py` (`is_stale`)
- Modify: `plugins/harness-opt/harness_opt/cli.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: `catalog_fingerprint`, `read_routing`
- Produces: `is_stale(data, fingerprints, now=None) -> bool` — 지문이 다르거나 `catalog_cutoff`가 30일 지남. cutoff 파싱 실패면 stale.  
  `install_hooks(cursor_hooks: Path, plugin_hooks: Path | None = None) -> dict` — Cursor `hooks.json`에 `beforeSubmitPrompt`와 `sessionEnd`만 harness-opt 줄을 추가/교체. 다른 command 바이트 유지. 파일 없으면 우리 줄만 생성. 식별자: 명령에 `harness-opt route` 또는 `harness-opt feedback`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hooks.py`:

```python
import json, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest
from harness_opt.hooks import install_hooks
from harness_opt.report import is_stale

class StaleTests(unittest.TestCase):
    def test_fingerprint_and_age(self):
        fresh = {'catalog_cutoff': datetime.now(timezone.utc).date().isoformat(),
                 'catalog_fingerprint': {'cursor': 'aaa'}}
        self.assertFalse(is_stale(fresh, {'cursor': 'aaa'}))
        self.assertTrue(is_stale(fresh, {'cursor': 'bbb'}))
        old = {'catalog_cutoff': (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat(),
               'catalog_fingerprint': {'cursor': 'aaa'}}
        self.assertTrue(is_stale(old, {'cursor': 'aaa'}))

class HookInstallTests(unittest.TestCase):
    def test_keeps_foreign_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'hooks.json'
            path.write_text(json.dumps({
                'version': 1,
                'hooks': {'beforeSubmitPrompt': [{'command': 'other'}],
                          'sessionEnd': [{'command': 'keep-me'}]},
            }))
            install_hooks(path)
            data = json.loads(path.read_text())
            starts = [x['command'] for x in data['hooks']['beforeSubmitPrompt']]
            ends = [x['command'] for x in data['hooks']['sessionEnd']]
            self.assertIn('other', starts)
            self.assertTrue(any('harness-opt route' in c for c in starts))
            self.assertIn('keep-me', ends)
            self.assertTrue(any('harness-opt feedback' in c or 'harness-opt route' in c for c in ends))
            again = path.read_bytes()
            install_hooks(path)
            self.assertEqual(len([c for c in json.loads(path.read_text())['hooks']['beforeSubmitPrompt']
                                  if 'harness-opt route' in c['command']]), 1)
            self.assertEqual(again, path.read_bytes()) or True  # second install is idempotent; bytes may refresh
```

마지막 `or True`는 넣지 마라. 두 번째 install 후 harness-opt 줄은 하나여야 하고 `other`/`keep-me`는 그대로다:

```python
            install_hooks(path)
            data = json.loads(path.read_text())
            self.assertEqual(sum('harness-opt route' in x['command'] for x in data['hooks']['beforeSubmitPrompt']), 1)
            self.assertEqual([x['command'] for x in data['hooks']['beforeSubmitPrompt'] if 'other' in x['command']], ['other'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_hooks -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`report.py`:

```python
from datetime import datetime, timezone, timedelta

def is_stale(data, fingerprints, now=None):
    now = now or datetime.now(timezone.utc)
    stored = data.get('catalog_fingerprint') or {}
    if any(stored.get(host) != fingerprints.get(host) for host in fingerprints):
        return True
    raw = data.get('catalog_cutoff') or ''
    try:
        cut = datetime.fromisoformat(raw).date()
    except ValueError:
        return True
    return (now.date() - cut).days >= 30
```

`hooks.py`는 JSON을 읽어 `beforeSubmitPrompt`/`sessionEnd` 리스트에서 `harness-opt route`/`harness-opt feedback`이 있는 항목을 빼고 우리 command를 한 줄씩 append.

Cursor start command (절대경로 대신 PATH의 `harness-opt`):

```
harness-opt route --host cursor --hook-stdin
```

`--hook-stdin`은 stdin JSON에서 prompt/model/effort/cwd를 읽어 `route()`에 넘기고, stdout은 항상 `{"continue": true}` 또는 질문이 있으면 `{"continue": true, "user_message": "..."}`. 파싱 실패해도 `{"continue": true}` exit 0.

Create `hooks/cursor-start.sh`:

```sh
#!/bin/sh
harness-opt route --host cursor --hook-stdin || printf '%s\n' '{"continue":true}'
```

Create `hooks/cursor-end.sh`:

```sh
#!/bin/sh
harness-opt route --host cursor --hook-event sessionEnd --hook-stdin || printf '%s\n' '{}'
```

종료는 `route`가 아니라 `feedback`을 물어야 한다. end 스크립트는:

```sh
#!/bin/sh
harness-opt feedback --hook-stdin || printf '%s\n' '{}'
```

`feedback --hook-stdin`: stdin에 prompt/model/effort가 없으면 skip. 있으면 질문 텍스트를 `user_message`로 내고, verdict가 stdin에 없으면 기록하지 않음 (`skipped`). 호스트가 답을 주면 `--verdict`로 다시 호출한다. 첫 구현: stdin JSON에 `verdict`가 있을 때만 `record_feedback`. 없으면 `{"user_message": "이번 작업(debug_investigate)에 grok-4.6 high 괜찮았나요? ok / weak / strong"}` 하고 파일은 그대로.

`install_hooks`가 가리키는 command는 위 스크립트의 절대경로 (`Path(__file__).resolve().parent.parent / 'hooks' / 'cursor-start.sh'`). 플러그인 패키지에서 `hooks/`를 package-data로 넣거나 스크립트를 `hooks.py`가 쓰는 고정 상대경로로 둔다. `pyproject.toml`의 package-data에 훅 스크립트가 없으면, command를 `harness-opt route --host cursor --hook-stdin` 한 줄로 심는다 (스크립트 파일 없이도 동작). **명령 한 줄을 JSON에 심는 쪽을 쓴다.** sh 파일은 없어도 된다. Task 파일 목록의 sh는 만들지 말고 CLI 플래그만 쓴다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest tests.test_hooks tests.test_feedback tests.test_route -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/harness_opt/hooks.py plugins/harness-opt/harness_opt/report.py plugins/harness-opt/harness_opt/cli.py plugins/harness-opt/harness_opt/feedback.py tests/test_hooks.py
git commit -m "$(cat <<'EOF'
Install start/end hooks without touching other hook entries.

EOF
)"
```

---

### Task 9: 스킬 문구와 플러그인 설명

**Files:**
- Modify: `plugins/harness-opt/skills/harness-opt/SKILL.md`
- Modify: `plugins/harness-opt/references/setup.md`
- Modify: `plugins/harness-opt/.claude-plugin/plugin.json`
- Modify: `plugins/harness-opt/.codex-plugin/plugin.json`
- Modify: `plugins/harness-opt/README.md` (명령 목록이 있는 단락만)
- Test: 없음. 기존 unittest 전부.

**Interfaces:**
- Consumes: Task 5–8 CLI
- Produces: 첫 질문이 **Skill optimize** 또는 **Class route**. Class route는 스펙 순서: stale이면 report 제안 → `report` → `hook install` → 유형 고르면 `calibrate`. `optimize`와 섞지 않음.

- [ ] **Step 1: Write the failing check**

문서에 `Class route`와 `harness-opt report`가 없으면 이 태스크는 미완이다. 테스트 대신 구현 후:

Run: `rg -n "Class route" plugins/harness-opt/skills/harness-opt/SKILL.md plugins/harness-opt/references/setup.md`  
Expected: 두 파일 모두 매치. 이 단계 전에는 없음.

- [ ] **Step 2: Confirm the string is missing**

Run: `rg -n "Class route" plugins/harness-opt/skills/harness-opt/SKILL.md plugins/harness-opt/references/setup.md || true`  
Expected: no matches (또는 Class calibrate만)

- [ ] **Step 3: Write the copy**

`SKILL.md` 첫 질문을 `Skill optimize` 또는 `Class route`로 바꾼다. Class route 블록:

```
1. harness-opt report --runner <runner>  (stale이면 재실행을 먼저 제안)
2. harness-opt hook install
3. catalog --view classes 후 calibratable 유형을 고르면 기존 calibrate
```

`setup.md`의 `Class calibrate` 제목을 `Class route`로 바꾸고 위 순서를 앞에 둔다. 그 다음이 기존 calibrate 질문(execution, repeats, time-limit).

plugin.json `description`을 한 줄로: `Classify session work, report model/effort below the host catalog ceiling, and ask via hooks.`

README에 `report` / `route` / `feedback` / `hook install` 네 줄만 추가.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PYTHONPATH=plugins/harness-opt python3 -m unittest discover -s tests -v`  
Expected: PASS. `optimize` assertion 실패 없음.

- [ ] **Step 5: Commit**

```bash
git add plugins/harness-opt/skills/harness-opt/SKILL.md plugins/harness-opt/references/setup.md plugins/harness-opt/.claude-plugin/plugin.json plugins/harness-opt/.codex-plugin/plugin.json plugins/harness-opt/README.md
git commit -m "$(cat <<'EOF'
Document Class route beside skill optimize.

EOF
)"
```

---

## Self-review

**Spec coverage**

| 스펙 | 태스크 |
| --- | --- |
| CLASS_EFFORT / 전체 세션 | 1 |
| 에이전트 모델 전부, 없는 ID 금지, cursor 측정 에러 | 2 |
| current 후보 = 목록 × 천장 이하, observed 유지 | 3 |
| pick_observed + feedback 반영 | 4, 7 |
| report 파일, verified 유지, 빈 히스토리 | 5 |
| 시작 훅 route, 높은 값만 질문, outcomes | 6 |
| 종료 훅 feedback, skip 시 파일 불변 | 7 |
| stale 30일/지문, hook install 다른 훅 유지 | 8 |
| Class route 스킬 문구 | 9 |
| `--runner cursor` calibrate 에러 | 이미 있음 + Task 2 measurement |

**Placeholders:** 없음. sh 파일은 Task 8에서 CLI 한 줄로 대체했다.

**Types:** `pick_observed` → `dict | None` with `model`/`effort`. `route` → `ask`/`message`/`source`/`recommended`. `record_feedback` → `status`. `native_models` → list of `{id, provider, efforts}`.
