# 기여 가이드

업무를 시작하기 전에
[`docs/TEAM_WORKFLOW_GUIDE.md`](docs/TEAM_WORKFLOW_GUIDE.md)에서 Jira-first와
GitHub-first 중 한 가지 경로를 선택합니다.

PR 제목은 `<gitmoji> <type>(optional-scope): <description>` 형식을 사용합니다.

예시:

```text
✨ feat: 추천 endpoint 추가
🐛 fix(model): 빈 입력 batch 처리
✅ test: 잘못된 inference 요청 검사 추가
```

`main`과 `development`의 모든 변경은 PR을 사용해야 합니다. 필수 검사를
통과하고 모든 review conversation을 해결합니다. 작업 브랜치 → `development`는
squash merge하고, `development` → `main` 승격은 merge commit을 사용합니다.
자동 브랜치 삭제는 사용하지 않으며 작업 브랜치는 sprint 정리 시 수동으로
삭제합니다.

# 코드 스타일

## formatter

- Python 코드 포맷팅은 [black](https://black.readthedocs.io/)을 사용합니다.

## 주석 / Docstring

- Python 주석(docstring)은 [Google Style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)을 따릅니다.
- 모듈, 클래스, public 함수/메서드에는 docstring을 작성합니다.
- 함수 docstring은 `Args`, `Returns`, `Raises` 섹션으로 구성합니다.

### 예시

```python
def check_severity(text: str, threshold: float = 0.5) -> bool:
    """입력 텍스트의 위험도를 판정한다.

    Args:
        text: 판정할 원본 텍스트.
        threshold: 위험으로 판단할 최소 점수. 기본값 0.5.

    Returns:
        위험도가 threshold 이상이면 True, 아니면 False.

    Raises:
        ValueError: text가 빈 문자열인 경우.
    """
```

