# DodamDodam AI

DodamDodam 캡스톤 프로젝트의 AI 서비스 저장소입니다.

`pyproject.toml`, `uv.lock` 또는 `requirements.txt`와 `.python-version`이
추가되면 CI가 실제 프로젝트 검사를 자동으로 실행합니다. Python 버전은
프로젝트가 직접 관리하며 CI에는 특정 버전을 미리 고정하지 않았습니다.

Organization 전체 협업 흐름은
[integration 저장소 문서](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/GITHUB_WORKFLOW.md)에서
관리합니다.

AI의 Jira Epic·Task 명명과 GitHub Issue·브랜치·PR 연결 규칙은
[`docs/JIRA_WORKFLOW.md`](docs/JIRA_WORKFLOW.md)를 따릅니다.

처음 업무를 시작하는 팀원은 Jira-first와 GitHub-first 선택 기준, 실제 branch,
commit, PR 예시가 포함된
[`docs/TEAM_WORKFLOW_GUIDE.md`](docs/TEAM_WORKFLOW_GUIDE.md)를 먼저 확인합니다.

기능 변경은 작업 브랜치에서 `development`로 squash merge합니다. 검증된
`development`는 보호된 PR과 사람의 승인을 거쳐 merge commit으로 `main`에
승격합니다. `main` 대상 PR의 source branch는 `development`만 허용하며 긴급
수정도 먼저 `development`에 반영합니다. `main` 반영이 완료되면 Bot PR이
integration의 `development`에서 AI commit SHA를 자동으로 갱신합니다.

2026-09-03에는 기존 AI 작업을 삭제하거나 재작성하지 않고, 먼저 반영되어 있던
`main` 계보를 merge commit으로 `development`에 연결해 장기 브랜치를
정렬했습니다.

# 파이프라인

STT → 안전검사(입력) → LLM → 안전검사(출력) → TTS

## 실행

```bash
pip install -r requirements.txt
python demo.py          # API 키 없이 안전 필터 검증
python -m pytest        # 테스트
```

여기까지는 키가 필요 없습니다.
실제 벤더를 호출하려면 `.env.example` 을 `.env` 로 복사하고 값을 채웁니다.

```bash
python smoke_gemini.py  # Gemini 실측 (지연/토큰/비용/캐시)
python list_models.py   # 사용 가능한 모델 목록
```

`.env` 로드는 진입점 스크립트의 책임입니다. 라이브러리(`llm/`, `stt/`)는 환경변수를
읽기만 하므로, 새 진입점을 만들면 `load_dotenv()` 를 직접 호출하세요.

## 테스트

```
tests/test_severity.py           severity-levels.md 종합 예시 표의 실행 가능한 사본
tests/test_safety_invariants.py  깨지면 실제 피해가 되는 항목만 모은 것
```

# 설계 규칙
1. **오케스트레이터는 벤더 SDK를 import 하지 않는다.** 전부 인터페이스를 경유합니다.
   - STT/LLM 벤치마크가 "구현체 추가"로 끝납니다.
2. **static_system 은 절대 턴마다 바뀌지 않는다.**
3. **모든 안전 판정을 로그에 남긴다.**
