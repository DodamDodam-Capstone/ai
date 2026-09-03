# AI 팀 업무 실행 가이드

이 문서는 AI 팀원이 Jira 또는 GitHub에서 업무를 시작해 `development` PR을
병합하고 완료 상태를 확인할 때 그대로 따라 하는 가이드입니다.

## 1. 이 저장소를 사용하는 업무

- Jira/GitHub 접두어: `[AI]`
- GitHub 저장소: `DodamDodam-Capstone/ai`
- 일반 PR 대상: `development`
- 필수 CI: `ai-quality`, `gitmoji-conventional-title`, `jira-issue-key`
- 알림 채널: `#ai-actions`

모델, 추론 API 내부 로직, 데이터 전처리, 평가, AI 테스트와 관련된 업무를 이
저장소에서 처리합니다. Frontend·Backend·통합 변경이 함께 필요하면 같은 Epic
아래에 `[FE]`, `[BE]`, `[INT]` Task를 별도로 만듭니다.

## 2. 시작 경로를 먼저 선택합니다

| 상황                         | 작업 방법                                                                |
| ---------------------------- | ------------------------------------------------------------------------ |
| Jira `[AI]` Task가 이미 있음 | Jira 키로 바로 branch와 PR을 만듭니다. GitHub Task Form은 열지 않습니다. |
| Jira Task가 없음             | GitHub의 `AI Task` 또는 `AI Bug` Form으로 Jira 업무를 자동 생성합니다.   |

이미 있는 Jira Task와 GitHub Issue Form을 함께 사용하면 Jira Task가 중복 생성될
수 있습니다. 한 업무에는 한 가지 시작 경로만 사용합니다.

## 3. Jira-first: Jira Task가 이미 있는 경우

예시 계획:

```text
Epic: SCRUM-200 [EPIC] 회원 인증 흐름 제공
Task: SCRUM-203 [AI] 이상 로그인 위험 점수 제공
```

### 3.1 작업 브랜치 생성

```bash
git switch development
git pull --ff-only
git switch -c feature/SCRUM-203-login-risk-score
```

### 3.2 commit과 PR 작성

```text
commit: ✨ feat(model): SCRUM-203 [AI] 로그인 위험 점수 계산 추가
PR:     ✨ feat(model): SCRUM-203 [AI] 로그인 위험 점수 계산 추가
base:   development
```

PR 본문에는 Jira 링크를 적습니다. GitHub Issue를 만들지 않은 Jira-first 업무에는
`Resolves #번호`를 넣지 않습니다.

```text
Jira: https://dodamdodam.atlassian.net/browse/SCRUM-203
관련 GitHub Issue: 없음 (Jira-first 업무)
```

### 3.3 병합 후 결과

1. 필수 CI와 리뷰를 통과합니다.
2. PR을 `development`에 squash merge합니다.
3. Jira의 Development 영역에 branch, commit, PR, build가 표시됩니다.
4. Jira Automation이 `SCRUM-203`을 `완료`로 전환합니다.
5. `#ai-actions`에서 source, target, PR, commit, actor, 결과를 확인합니다.

이 경로에는 GitHub Issue가 없으므로 Jira Task만 완료됩니다.

## 4. GitHub-first: GitHub Issue에서 Jira Task를 만드는 경우

### 4.1 Issue Form 작성

`New issue`에서 `AI Task`를 선택합니다.

```text
제목: [AI] 로그인 위험 점수 평가 지표 추가
상위 Jira 키: SCRUM-200
완료 목표: 위험 점수 모델의 기준 성능을 반복 측정할 수 있다.
완료 조건:
- [ ] 평가 dataset과 지표 정의
- [ ] 재현 가능한 평가 테스트 통과
- [ ] development 대상 PR 준비
```

Issue를 열면 자동화가 Jira Task를 만들고 제목을 다음과 같이 변경합니다.

```text
ai#123 SCRUM-209 [AI] 로그인 위험 점수 평가 지표 추가
```

자동 결과:

- Jira `SCRUM-209` Task 생성 및 `SCRUM-200` Epic의 child로 연결
- GitHub Issue에 Jira 링크 댓글 추가
- `jira-linked` 레이블 추가
- Slack 전송 성공 시 `jira-notified` 레이블 추가
- `#ai-actions`에 GitHub Issue → Jira 연결 결과 전송

### 4.2 자동 생성된 키로 작업

```text
branch: feature/SCRUM-209-risk-score-metrics
commit: ✅ test(model): SCRUM-209 [AI] 위험 점수 평가 지표 추가
PR:     ✅ test(model): SCRUM-209 [AI] 위험 점수 평가 지표 추가
base:   development
```

PR 본문:

```text
Jira: https://dodamdodam.atlassian.net/browse/SCRUM-209
Resolves #123
```

PR merge 후 `close-linked-issues`가 `ai#123`을 닫고, Jira Automation이
`SCRUM-209`를 `완료`로 전환합니다.

## 5. Bug 업무 예시

```text
GitHub Form: AI Bug
Issue: SCRUM-210 [AI] 빈 batch 입력에서 추론이 실패함
branch: fix/SCRUM-210-empty-batch
commit: 🐛 fix(inference): SCRUM-210 [AI] 빈 batch 입력 처리
PR: 🐛 fix(inference): SCRUM-210 [AI] 빈 batch 입력 처리
```

재현 입력과 기대·실제 결과를 Issue에 작성하되 개인정보, 원본 민감 dataset,
API token, 모델 저장소 credential은 첨부하지 않습니다.

## 6. PR 검증과 병합 규칙

- branch와 PR 제목에는 같은 `SCRUM-번호`를 정확히 하나 넣습니다.
- `development` 대상 PR 제목에는 `[AI]`만 정확히 하나 넣습니다.
- Gitmoji는 의미에 맞게 자유롭게 선택하고 `feat`, `fix`, `docs`, `test` 등의
  Conventional Commit type을 사용합니다.
- GitHub Issue가 있을 때만 같은 저장소 Issue를 `Resolves #번호`로 연결합니다.
- `ai-quality`와 모든 필수 검사를 통과합니다.
- 마지막 push를 하지 않은 다른 팀원의 승인을 받습니다.
- 모든 review conversation을 해결한 뒤 squash merge합니다.
- `development`와 `main`에는 직접 push하지 않습니다.
- `main` 대상 PR은 `development`에서만 만들며 긴급 수정도 같은 승격 경로를
  사용합니다.

## 7. 완료 확인

- GitHub-first: GitHub Issue `Closed`와 Jira Task `완료`를 모두 확인합니다.
- Jira-first: Jira Task `완료`와 Jira Development의 `MERGED` PR을 확인합니다.
- Team Board Gantt에서 업무가 사라지면 `Show completed tickets`를 켭니다.
- Epic은 모든 `[FE]`, `[BE]`, `[AI]`, `[INT]` child Task와 통합 검증이 끝난 뒤
  sprint review에서 수동 완료합니다.

## 8. 문제 발생 시

- `jira-issue-key` 실패: branch와 PR의 Jira 키, `[AI]`, target branch를 확인합니다.
- Jira 자동 생성 실패: `GitHub Issue to Jira`를 `main`에서 Issue 번호로 재실행합니다.
- 중복 Jira Task가 의심됨: 새 Task를 만들지 말고 `jira-linked` 댓글과 Jira의
  `github-ai-<issue-number>` 레이블을 확인합니다.
- Issue가 닫히지 않음: PR 본문의 `Resolves #번호`, 같은 저장소 Issue인지,
  `Close Linked Issues` 실행 결과를 확인합니다.

Organization 전체 흐름과 다른 저장소 예시는
[integration 팀 가이드](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/TEAM_WORKFLOW_GUIDE.md)를
기준으로 합니다.
