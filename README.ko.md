# 왜 Fable을 막았어?

[English](README.md) · **한국어**

![왜 Fable을 막았어?](assets/social-preview.jpg)

**AI 코딩 에이전트에게 "spec 먼저" 규율을 강제하는 게이트.**
spec을 쓰고 통과하기 전엔 **코드 편집 차단.** Claude Code + Codex.

> `git clone https://github.com/SihyeonJeon/why-was-fable-banned && cd why-was-fable-banned && sh install.sh`

---

## 한눈에

- **무엇** · 계획 없이 코드 짜는 걸 막고, 변경마다 의사결정 기록을 남김
- **왜** · 세션 끝나면 추론 증발 / 급하면 검증 생략 → 그 규율을 **비선택·감사가능**으로
- **아닌 것** · 능력 부스터 아님. 프로세스 강제지 더 똑똑하게 만들진 않음

---

## 출처 · Fable 세션에서 수집·추출·코드화

추측이 아니라, **Fable로 실제 엔지니어링 작업을 수행하며 수집한 의사결정 데이터**에서 나옴.
원시 로그를 구조화 스키마로 추출 → 교차검증으로 일반화 → 게이트로 코드화 → runtime 강제:

```
Fable 세션 (실작업, 7 프로젝트)
   │
   ├─ ① 수집   hook 자동 기록 → 42 trace · 2층(런타임 I/O + 의사결정 출력)
   ├─ ② 추출   원시 로그 → 구조화 의사결정 스키마 (spec / decision_events)
   ├─ ③ 일반화 19 trace → 8축 의사결정 패턴 · 4 추출기 + Codex 교차검증(과장 정정)
   ├─ ④ 코드화 패턴 → 게이트룰(deterministic) + LLM judge(cross-family·phase-aware) + 절차 프롬프트
   ├─ ⑤ 삽입   hook runtime 주입 (PreToolUse exit-2 차단 / Codex worktree-accept)
   └─ ⑥ 검증   토큰·품질·적대 벤치 + 23 테스트 (게이밍·우회·malformed 강건화)
```

> 관측 가능한 산출물만 · 사적 추론·CoT 미수집, 로컬·시크릿 마스킹.

## 설치

```sh
git clone https://github.com/SihyeonJeon/why-was-fable-banned && cd why-was-fable-banned && sh install.sh
```
필요: `python3` · 끄기: `touch .forge/OFF` / `FORGE_BYPASS=1` · 제거: `sh install.sh --uninstall`

---

## 데이터 · 추출 형식

원시 로그가 아니라 **구조화된 의사결정 스키마**로 추출. 코딩 세션을 두 층으로 캡처:

- **런타임 I/O** (hook 자동) · 프롬프트·파일읽기·명령+출력·편집·플랜·서브에이전트 호출
- **의사결정 출력** (구조화 강제) · 아래 스키마로:

```jsonc
spec = {
  restated_goal,                                   // 글자 아닌 의도 + 제약 봉투
  non_goals[],                                     // 부정으로 스코프 정의
  must_read[{ path, authority_reason }],           // 권위(계약/경계) 기반 컨텍스트
  rejected_alternatives[{ category, broken_boundary }],  // 깨지는 경계로 기각
  risks[{ severity, mitigation, acceptance_ref }], // blast-radius + 실행가능 완화
  acceptance_criteria[{ verify:{type,value} }],    // 실행가능 검증
  forbidden_paths[]                                // 건드리면 안 되는 경계
}
decision_events = { hypothesis_before, decision, rejected_options, confidence_before→after, observation_refs }
```

여러 세션을 **8축 의사결정 패턴**(목표해석·컨텍스트·제약·대안·위험·acceptance·검증루프·실패처리)으로
일반화 + **교차검증**(도메인 횡단 수렴만 채택), 품질은 **0–2 룹릭**으로 정량화.

## 활용

추출 패턴을 **3형태로 코드화 → 3중 방어**:

| 형태 | 레이어 | 검사 |
|---|---|---|
| 게이트 룰 (deterministic) | `gates/forge_gate.py` | **형식** · 필드·경로실존·forbidden·fail-closed |
| 룹릭 (LLM judge, cross-family) | `gates/forge_judge.py` | **의미** · 0–2 채점, 게이밍 탐지 |
| 절차 프롬프트 | `prompts/` · `rubric/` | **정확성** · 숨은 채점기 벤치 |

등급 자동화(LIGHT/STANDARD/HEAVY)로 토큰 절약 · 보안·결제·마이그만 풀 게이트.

---

## 에이전트 삽입

**hook 기반 runtime 주입** · user-레벨 설정에 등록 → 전 프로젝트·세션·서브에이전트·오케스트레이션 워커가 상속:

| hook | 동작 |
|---|---|
| `UserPromptSubmit` | 작업 프롬프트 감지 → `.forge/` task 자동 scaffold + 절차 주입 |
| `PreToolUse` | 편집 도구(Edit/Write/apply_patch) 가로채 spec 게이트 검사 → 미통과면 **exit 2 차단** |
| `PostToolUse` | 편집 경로 기록 → `forbidden_paths` 위반 검증 |
| `Stop` | done 게이트 미충족 시 경고 |

- **Claude Code** · native 훅이 발화 → **in-session 하드차단** (한 세션, spec만 추가, LIGHT <2× 토큰)
- **Codex** · `forge-codex-accept "<goal>" --repo <dir>`: 버리는 git worktree서 작업 →
  **게이트 통과분만 실 repo에 apply** (unspeced/forbidden 작업이 repo에 도달 못 함)
- **모델 무관** · 게이트 엔진은 stdlib `python3`, 어떤 모델에도 동일 강제. 상태는 프로젝트 `.forge/`에 로컬

---

## 구성

`gates/` 엔진+judge · `adapters/` 설치(CC/Codex) · `prompts/`·`rubric/` 절차 · `bench/`·`tests/` (23개)

로컬 전용 · 능력 향상 미입증(가치는 프로세스·감사·안전) · MIT
