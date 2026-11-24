"""일반 작업의 Jira 계약과 main 승격의 버전 계약을 구분해서 검사한다."""

import os
import re
import sys

from release import read_version, validate_notes, validate_release_title


def validate():
    """main의 source·파트·버전 검사는 일반 Bot 예외보다 먼저 적용한다."""
    title, head, base = (os.environ[name] for name in ("PR_TITLE", "HEAD_REF", "BASE_REF"))
    prefixes = re.findall(r"\[(?:FE|BE|AI|INT)\]", title)
    if base == "main":
        if head != "development" or os.environ["HEAD_REPOSITORY"] != os.environ["GITHUB_REPOSITORY"]:
            raise ValueError("main 대상 PR은 같은 저장소의 development에서만 생성할 수 있습니다.")
        version = read_version()
        validate_release_title(title, version)
        validate_notes(os.environ.get("PR_BODY", ""))
        return f"Release version verified: {version}"

    if base != "development":
        raise ValueError("지원하지 않는 PR 대상 브랜치입니다.")
    if os.environ["ACTOR"] == "dependabot[bot]" or head.startswith("bot/"):
        return "기존 자동화 작업 PR은 Jira 키 검사를 건너뜁니다."
    head_keys = re.findall(r"\bSCRUM-\d+\b", head)
    title_keys = re.findall(r"\bSCRUM-\d+\b", title)
    if len(head_keys) != 1 or len(title_keys) != 1 or head_keys != title_keys:
        raise ValueError("브랜치와 PR 제목에 일치하는 Jira 키가 정확히 하나 필요합니다.")
    if prefixes != ["[AI]"]:
        raise ValueError("AI 작업 PR 제목에는 [AI]를 정확히 하나 표시해야 합니다.")
    return f"Jira key verified: {head_keys[0]}"


def main():
    """계약 위반과 VERSION 누락을 명확한 실패 코드로 전달한다."""
    try:
        print(validate())
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
