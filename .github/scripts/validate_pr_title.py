import os
import re
import sys
import unicodedata


TYPE_PATTERN = (
    r"(?:feat|fix|refactor|docs|test|ci|chore|perf|security|revert|style|build|deps)"
    r"(?:\([a-z0-9._/-]+\))?"
)


def is_gitmoji(token: str) -> bool:
    if re.fullmatch(r":[a-z0-9_+-]+:", token):
        return True
    allowed_categories = {"So", "Sk", "Mn", "Cf"}
    return bool(token) and any(
        unicodedata.category(char) == "So" for char in token
    ) and all(
        unicodedata.category(char) in allowed_categories for char in token
    )


def main() -> int:
    title = os.environ.get("PR_TITLE", "").strip()
    parts = title.split(" ", 1)
    valid = (
        len(parts) == 2
        and is_gitmoji(parts[0])
        and re.fullmatch(rf"{TYPE_PATTERN}: \S.+", parts[1]) is not None
    )
    if not valid:
        print("Invalid PR title.")
        print("Expected: <gitmoji> <type>(optional-scope): <description>")
        print("Example: 🐛 fix(auth): refresh expired access tokens")
        return 1

    print(f"Valid PR title: {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
