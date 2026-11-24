"""버전·PR 계약과 외부 쓰기 없는 릴리스 회귀 검사."""

import importlib
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
OTHER_SHA = "b" * 40
REPO = "DodamDodam-Capstone/ai"
NOTES = "## 스프린트 작업\n\n### 테스트 스프린트\n- [SCRUM-191](https://dodamdodam.atlassian.net/browse/SCRUM-191) 릴리스 자동화\n"


class PullRequestContractTests(unittest.TestCase):
    # 실제 CLI 경계에서 일반 작업과 승격 예외가 서로 섞이지 않는지 확인한다.
    def check_pr(self, *, title="🚀 chore(release): [AI] v0.1.0 스프린트 릴리스",
                 head="development", base="main", actor="developer", version="0.1.0\n",
                 head_repo=REPO, body=NOTES):
        with tempfile.TemporaryDirectory() as directory:
            if version is not None:
                (Path(directory) / "VERSION").write_text(version)
            return subprocess.run(
                [sys.executable, str(ROOT / ".github/scripts/validate_pr_contract.py")],
                cwd=directory, capture_output=True, text=True,
                env={**os.environ, "PR_TITLE": title, "PR_BODY": body, "HEAD_REF": head, "BASE_REF": base,
                     "ACTOR": actor, "HEAD_REPOSITORY": head_repo, "GITHUB_REPOSITORY": REPO},
            )

    def test_release_title_accepts_version_without_jira_key(self):
        result = self.check_pr()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_rejects_wrong_source_part_version_and_bot_bypass(self):
        for changes in [
            {"head": "feature/SCRUM-191-release"}, {"head_repo": "someone/ai"},
            {"head": "bot/update", "actor": "dependabot[bot]"},
            {"title": "🚀 chore(release): [FE] v0.1.0 릴리스"},
            {"title": "🚀 chore(release): [AI] [AI] v0.1.0 릴리스"},
            {"title": "🚀 chore(release): [AI] v0.1.0 [INT] 릴리스"},
            {"title": "🚀 chore(release): [AI] v0.2.0 릴리스"},
            {"title": "🚀 chore(release): [AI] 릴리스"},
            {"title": "🚀 chore(release): [AI] v0.1.0 릴리스 v0.2.0"},
            {"version": "01.1.0"}, {"version": "0.1.0-rc.1"}, {"version": None},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.check_pr(**changes).returncode, 1)

    def test_regular_pr_still_requires_matching_key_and_single_ai_prefix(self):
        title = "🔧 ci: SCRUM-191 [AI] 릴리스 자동화"
        base = dict(title=title, head="feature/SCRUM-191-release", base="development")
        self.assertEqual(self.check_pr(**base).returncode, 0)
        for changes in [
            {"title": title.replace("SCRUM-191 ", "")},
            {"title": title.replace("191", "192")},
            {"title": title.replace("[AI]", "[FE]")},
            {"title": title.replace("[AI]", "[AI] [AI]")},
            {"head": "feature/release"},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.check_pr(**{**base, **changes}).returncode, 1)

    def test_existing_bot_exception_only_applies_to_development(self):
        self.assertEqual(self.check_pr(base="development", head="dependabot/github_actions/update",
                                      actor="dependabot[bot]", title="⬆️ deps: update").returncode, 0)

    def test_main_pr_requires_nonempty_sprint_task_section(self):
        for body in ("", "설명만 있음", "## 스프린트 작업\n<!-- SCRUM-191 -->", "## 스프린트 작업\n\n## 검증\n통과"):
            with self.subTest(body=body):
                self.assertEqual(self.check_pr(body=body).returncode, 1)


class FakeGitHub:
    """GitHub ref의 생성 전용 의미를 보존하는 메모리 경계. 실제 네트워크는 쓰지 않는다."""

    def __init__(self):
        self.refs = {}
        self.releases = []
        self.tags = {}
        self.writes = []
        self.fail_release_once = False
        self.pulls = [{"number": 1, "title": "🚀 chore(release): [AI] v0.1.0 스프린트 릴리스", "merge_commit_sha": SHA, "merged_at": "2026-11-17T12:31:00Z",
                       "base": {"ref": "main"}, "head": {"ref": "development", "repo": {"full_name": REPO}},
                       "body": NOTES}]

    def __call__(self, endpoint, payload=None, *, paginate=False):
        path = endpoint.removeprefix(f"repos/{REPO}/")
        if payload is None:
            if path.startswith("git/matching-refs/"):
                prefix = "refs/" + path.removeprefix("git/matching-refs/")
                return [{"ref": ref, "object": obj} for ref, obj in self.refs.items() if ref.startswith(prefix)]
            if path.startswith("git/tags/"):
                return {"object": self.tags[path.removeprefix("git/tags/")]}
            if path == "releases?per_page=100":
                return list(self.releases)
            if path == f"commits/{SHA}/pulls?per_page=100":
                return self.pulls
        elif path == "git/refs":
            if payload["ref"] in self.refs:
                raise RuntimeError("Reference already exists")
            self.refs[payload["ref"]] = {"type": "commit", "sha": payload["sha"]}
            self.writes.append((path, payload))
            return {"ref": payload["ref"]}
        elif path == "releases":
            if self.fail_release_once:
                self.fail_release_once = False
                raise RuntimeError("GitHub unavailable")
            result = {**payload, "html_url": f"https://github.com/{REPO}/releases/tag/{payload['tag_name']}"}
            self.releases.append(result)
            self.writes.append((path, payload))
            return result
        raise AssertionError(f"Unexpected API: {endpoint}")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        # 실제 구현을 호출하되 인증이 필요한 API 경계만 교체한다.
        self.release = importlib.import_module("release")
        self.github = FakeGitHub()
        self.api = patch.object(self.release, "api", self.github)
        self.api.start()
        self.addCleanup(self.api.stop)

    def test_create_then_rerun_preserves_refs_and_release(self):
        url = self.release.publish(REPO, SHA, "0.1.0")
        self.assertTrue(url.endswith("/releases/tag/v0.1.0"))
        self.assertEqual(set(self.github.refs), {"refs/heads/release/v0.1.0", "refs/tags/v0.1.0"})
        self.assertTrue(all(obj["sha"] == SHA for obj in self.github.refs.values()))
        self.assertEqual(self.github.releases[0]["target_commitish"], SHA)
        self.assertTrue(self.github.releases[0]["generate_release_notes"])
        self.assertEqual(self.release.publish(REPO, SHA, "0.1.0"), url)
        self.assertEqual(len(self.github.writes), 3)

    def test_release_contains_notes_from_its_promotion_pr(self):
        self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.releases[0].get("body"), NOTES)
        self.github.pulls[0]["body"] = NOTES + "PR 편집 내용"
        self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.releases[0]["body"], NOTES)
        self.assertEqual(len(self.github.writes), 3)

    def test_missing_or_wrong_promotion_pr_fails_before_ref_creation(self):
        original = deepcopy(self.github.pulls[0])
        variants = [[], [original, original]]
        for field, value in (("merge_commit_sha", OTHER_SHA), ("merged_at", None), ("body", ""),
                             ("title", "🚀 chore(release): [BE] v0.1.0 스프린트 릴리스"),
                             ("body", "## 스프린트 작업\n\n## 검증\n통과"),
                             ("base", {"ref": "development"}),
                             ("head", {"ref": "development", "repo": {"full_name": "someone/ai"}})):
            variants.append([{**original, field: value}])
        for pulls in variants:
            with self.subTest(pulls=pulls):
                self.github.pulls = pulls
                with self.assertRaises(ValueError):
                    self.release.publish(REPO, SHA, "0.1.0")
                self.assertEqual(self.github.writes, [])

    def test_conflicting_branch_or_tag_fails_before_any_write(self):
        for ref in ("refs/heads/release/v0.1.0", "refs/tags/v0.1.0"):
            with self.subTest(ref=ref):
                self.github.refs = {ref: {"type": "commit", "sha": OTHER_SHA}}
                with self.assertRaisesRegex(ValueError, "another commit"):
                    self.release.publish(REPO, SHA, "0.1.0")
                self.assertEqual(self.github.writes, [])

    def test_partial_failure_can_be_resumed_without_moving_refs(self):
        self.github.fail_release_once = True
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(len(self.github.refs), 2)
        self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(len(self.github.writes), 3)

    def test_exact_ref_match_does_not_confuse_version_prefix(self):
        self.github.refs["refs/tags/v0.1.01"] = {"type": "commit", "sha": OTHER_SHA}
        self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.refs["refs/tags/v0.1.0"]["sha"], SHA)

    def test_annotated_tag_is_compared_by_commit(self):
        self.github.refs["refs/tags/v0.1.0"] = {"type": "tag", "sha": "c" * 40}
        self.github.tags["c" * 40] = {"type": "commit", "sha": SHA}
        self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.refs["refs/tags/v0.1.0"]["type"], "tag")

    def test_api_failure_is_not_treated_as_missing_ref(self):
        with patch.object(self.release, "api", side_effect=RuntimeError("403 Forbidden")):
            with self.assertRaisesRegex(RuntimeError, "403"):
                self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.writes, [])

    def test_invalid_inputs_and_draft_release_are_rejected(self):
        for version in ("01.1.0", "0.1", "0.1.0-rc.1", "0.1.0\nx", "../../x"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.release.publish(REPO, SHA, version)
        with self.assertRaises(ValueError):
            self.release.publish(REPO, "main", "0.1.0")
        self.github.releases = [{"tag_name": "v0.1.0", "draft": True, "prerelease": False}]
        with self.assertRaisesRegex(ValueError, "draft|prerelease"):
            self.release.publish(REPO, SHA, "0.1.0")
        self.assertEqual(self.github.writes, [])

    def test_cli_rejects_pull_request_and_manual_events_before_api_calls(self):
        for event, ref in (("pull_request", "refs/pull/1/merge"), ("workflow_dispatch", "refs/heads/main"),
                           ("push", "refs/heads/development")):
            with self.subTest(event=event, ref=ref), patch.dict(os.environ, {
                "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref,
                "GITHUB_REPOSITORY": REPO, "GITHUB_SHA": SHA,
            }):
                self.assertEqual(self.release.main(), 1)
        self.assertEqual(self.github.writes, [])


if __name__ == "__main__":
    unittest.main()
