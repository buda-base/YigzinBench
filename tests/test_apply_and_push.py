"""Script tests for .github/scripts/apply-and-push.sh."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "apply-and-push.sh"


class ApplyAndPushTest(unittest.TestCase):
    def _git(self, *args: str, cwd: Path, env: dict | None = None) -> None:
        subprocess.check_call(
            ["git", *args],
            cwd=cwd,
            env=env or os.environ,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _setup_repos(self, tmp: Path) -> tuple[Path, Path, Path, dict]:
        bare = tmp / "origin.git"
        work = tmp / "work"
        rival = tmp / "rival"
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        gh_log = tmp / "gh.log"
        gh = bin_dir / "gh"
        gh.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo "$@" >> "{gh_log}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

        subprocess.check_call(["git", "init", "--bare", str(bare)], stdout=subprocess.DEVNULL)
        self._git("clone", str(bare), str(work), cwd=tmp)
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GIT_AUTHOR_NAME": "tester",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "tester",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GH_TOKEN": "dummy",
        }
        # Seed main with a tracked tree the script expects.
        (work / "submissions").mkdir()
        (work / "submissions" / "_removed.json").write_text('{"removed": []}\n', encoding="utf-8")
        (work / "leaderboard").mkdir()
        (work / "leaderboard" / "leaderboard.json").write_text("{}\n", encoding="utf-8")
        (work / "README.md").write_text(
            "<!-- leaderboard:start -->\n<!-- leaderboard:end -->\n",
            encoding="utf-8",
        )
        scripts = work / ".github" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, scripts / "apply-and-push.sh")
        self._git("add", ".", cwd=work, env=env)
        self._git("commit", "-m", "seed", cwd=work, env=env)
        # Ensure branch is main
        self._git("branch", "-M", "main", cwd=work, env=env)
        self._git("push", "-u", "origin", "main", cwd=work, env=env)
        self._git("clone", str(bare), str(rival), cwd=tmp)
        self._git("checkout", "main", cwd=rival, env=env)
        return bare, work, rival, {**env, "gh_log": str(gh_log)}

    def _run(self, work: Path, env: dict, message: str, command: list[str]) -> subprocess.CompletedProcess:
        gh_out = work / "github_output"
        if gh_out.exists():
            gh_out.unlink()
        run_env = {**env, "GITHUB_OUTPUT": str(gh_out)}
        return subprocess.run(
            ["bash", str(work / ".github" / "scripts" / "apply-and-push.sh"), message, "--", *command],
            cwd=work,
            env=run_env,
            capture_output=True,
            text=True,
        )

    def _result(self, work: Path) -> str:
        text = (work / "github_output").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("result="):
                return line.split("=", 1)[1]
        self.fail(f"no result in {text!r}")

    def test_committed_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, _, env = self._setup_repos(Path(tmp))
            cmd = [
                "bash", "-c",
                'mkdir -p submissions/issue-1 && echo hi > submissions/issue-1/meta.json && '
                'echo "{}" > leaderboard/leaderboard.json',
            ]
            proc = self._run(work, env, "Publish test", cmd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self._result(work), "committed")
            self.assertIn("workflow run deploy-pages.yml --ref main", Path(env["gh_log"]).read_text())

    def test_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, _, env = self._setup_repos(Path(tmp))
            proc = self._run(work, env, "x", ["bash", "-c", "exit 10"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self._result(work), "refused")
            self.assertFalse(Path(env["gh_log"]).exists() and Path(env["gh_log"]).read_text().strip())

    def test_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, _, env = self._setup_repos(Path(tmp))
            proc = self._run(work, env, "x", ["bash", "-c", "true"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self._result(work), "unchanged")

    def test_retry_then_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, rival, env = self._setup_repos(Path(tmp))
            # First push from work will fail because rival races ahead after we
            # start; use a command that on attempt 1 also lets rival push.
            marker = Path(tmp) / "attempt"
            marker.write_text("0", encoding="utf-8")
            script = textwrap.dedent(
                f"""\
                #!/bin/bash
                n=$(cat "{marker}")
                echo $((n+1)) > "{marker}"
                if [ "$n" -eq 0 ]; then
                  # Race: advance origin from the rival clone before our push.
                  (cd "{rival}" && mkdir -p submissions/x && echo race > submissions/x/f \\
                    && git add submissions && git -c user.name=r -c user.email=r@e.com \\
                    commit -m race && git push origin main) >/dev/null 2>&1 || true
                fi
                mkdir -p submissions/issue-9
                echo ok > submissions/issue-9/meta.json
                echo '{{}}' > leaderboard/leaderboard.json
                """
            )
            cmd_path = Path(tmp) / "mutate.sh"
            cmd_path.write_text(script, encoding="utf-8")
            cmd_path.chmod(cmd_path.stat().st_mode | stat.S_IEXEC)
            proc = self._run(work, env, "Publish race", ["bash", str(cmd_path)])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual(self._result(work), "committed")
            self.assertGreaterEqual(int(marker.read_text()), 2)

    def test_push_failed_five_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            bare, work, _, env = self._setup_repos(Path(tmp))
            # Reject all pushes by removing the receive capability: use a
            # pre-receive hook that always fails.
            hook = bare / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\necho denied >&2\nexit 1\n", encoding="utf-8")
            hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
            proc = self._run(
                work,
                env,
                "will fail",
                ["bash", "-c", "echo change > submissions/_removed.json"],
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertEqual(self._result(work), "push_failed")


if __name__ == "__main__":
    unittest.main()
