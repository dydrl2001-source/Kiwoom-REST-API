import subprocess
import tempfile
import unittest
from pathlib import Path

import preflight_python


class MarketOsPreflightSourceTest(unittest.TestCase):
    def test_literal_escaped_newline_between_imports_is_rejected(self):
        source = r"import hmac\nimport os" + "\n"
        issues = preflight_python.validate_source(
            source, "market_radar/broken.py"
        )
        self.assertTrue(
            any(issue.kind == "literal-escaped-newline" for issue in issues)
        )
        self.assertTrue(any(issue.kind == "syntax" for issue in issues))

    def test_escaped_newline_inside_string_is_allowed(self):
        source = r'message = "first\nsecond"' + "\n"
        issues = preflight_python.validate_source(
            source, "market_radar/valid.py"
        )
        self.assertEqual([], issues)

    def test_real_newline_between_imports_is_allowed(self):
        source = "import hmac\nimport os\n"
        issues = preflight_python.validate_source(
            source, "market_radar/valid.py"
        )
        self.assertEqual([], issues)


class MarketOsPreflightGitSelectionTest(unittest.TestCase):
    def test_collects_staged_unstaged_and_untracked_python(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            radar = root / "market_radar"
            radar.mkdir()
            (radar / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
            (radar / "ignore.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "preflight@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Preflight Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "base"], cwd=root, check=True
            )

            (radar / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
            (radar / "staged.py").write_text(
                "STAGED = True\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "market_radar/staged.py"],
                cwd=root,
                check=True,
            )
            (radar / "untracked.py").write_text(
                "UNTRACKED = True\n", encoding="utf-8"
            )
            (radar / "ignore.txt").write_text(
                "not python\n", encoding="utf-8"
            )

            files = preflight_python.collect_python_files(root, "HEAD")
            rels = {path.relative_to(root).as_posix() for path in files}
            self.assertEqual(
                {
                    "market_radar/staged.py",
                    "market_radar/tracked.py",
                    "market_radar/untracked.py",
                },
                rels,
            )


if __name__ == "__main__":
    unittest.main()
