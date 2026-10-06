#!/usr/bin/env python3
"""Shared lightweight Python syntax preflight for Market Radar.

Local default: check Python files changed relative to the current upstream plus
staged, unstaged, and untracked Market Radar Python files.
CI: pass --base <sha/ref> so the same checker evaluates the event diff.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MARKET_RADAR_PREFIX = "market_radar/"


@dataclass(frozen=True)
class Issue:
    path: str
    line: int
    column: int
    kind: str
    message: str


def _run_git(repo_root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return proc.stdout.strip()


def _valid_ref(repo_root: Path, ref: str | None) -> str | None:
    if not ref or set(ref) == {"0"}:
        return None
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return ref if proc.returncode == 0 else None


def resolve_base(repo_root: Path, explicit: str | None = None) -> str | None:
    candidates: list[str | None] = [
        explicit,
        os.getenv("MARKET_RADAR_PREFLIGHT_BASE"),
    ]
    upstream = _run_git(
        repo_root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    if upstream:
        candidates.append(upstream)
    candidates.extend(["origin/main", "main", "HEAD^"])
    for candidate in candidates:
        valid = _valid_ref(repo_root, candidate)
        if valid:
            return valid
    return None


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _is_market_radar_python(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(MARKET_RADAR_PREFIX) and normalized.endswith(".py")


def collect_python_files(
    repo_root: Path,
    base: str | None = None,
    *,
    all_files: bool = False,
) -> list[Path]:
    paths: set[str] = set()
    if all_files:
        paths.update(
            _lines(
                _run_git(
                    repo_root,
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    "market_radar",
                )
            )
        )
    else:
        resolved = resolve_base(repo_root, base)
        if resolved:
            paths.update(
                _lines(
                    _run_git(
                        repo_root,
                        "diff",
                        "--name-only",
                        "--diff-filter=ACMR",
                        f"{resolved}..HEAD",
                        "--",
                        "market_radar",
                    )
                )
            )
        else:
            # No usable history/upstream: fail safe by checking every visible file.
            paths.update(
                _lines(
                    _run_git(
                        repo_root,
                        "ls-files",
                        "--cached",
                        "--others",
                        "--exclude-standard",
                        "--",
                        "market_radar",
                    )
                )
            )

        paths.update(
            _lines(
                _run_git(
                    repo_root,
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=ACMR",
                    "--",
                    "market_radar",
                )
            )
        )
        paths.update(
            _lines(
                _run_git(
                    repo_root,
                    "diff",
                    "--name-only",
                    "--diff-filter=ACMR",
                    "--",
                    "market_radar",
                )
            )
        )
        paths.update(
            _lines(
                _run_git(
                    repo_root,
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "--",
                    "market_radar",
                )
            )
        )

    result = []
    for rel in sorted(path for path in paths if _is_market_radar_python(path)):
        full = repo_root / rel
        if full.is_file():
            result.append(full)
    return result


def find_literal_escaped_newlines(source: str, display_path: str) -> list[Issue]:
    """Find literal \\n/\\r\\n tokens accidentally placed in Python code.

    Strings and comments are naturally excluded because their backslashes are
    part of STRING/COMMENT tokens rather than ERRORTOKENs.
    """
    issues: list[Issue] = []
    reader = io.StringIO(source).readline
    try:
        for token in tokenize.generate_tokens(reader):
            if token.type != tokenize.ERRORTOKEN or token.string != "\\":
                continue
            physical_line = token.line or ""
            col = token.start[1]
            suffix = physical_line[col:]
            escaped = (
                "\\r\\n"
                if suffix.startswith("\\r\\n")
                else "\\n"
                if suffix.startswith("\\n")
                else None
            )
            if escaped:
                issues.append(
                    Issue(
                        display_path,
                        token.start[0],
                        col + 1,
                        "literal-escaped-newline",
                        f"literal escaped newline {escaped!r} appears in Python code; use a real line break",
                    )
                )
    except (tokenize.TokenError, IndentationError):
        # compile() below provides the authoritative syntax error.
        pass
    return issues


def validate_source(source: str, display_path: str) -> list[Issue]:
    issues = find_literal_escaped_newlines(source, display_path)
    try:
        compile(source, display_path, "exec", dont_inherit=True)
    except (SyntaxError, ValueError, OverflowError) as exc:
        line = getattr(exc, "lineno", None) or 1
        column = getattr(exc, "offset", None) or 1
        message = getattr(exc, "msg", None) or str(exc)
        issues.append(Issue(display_path, line, column, "syntax", message))
    return issues


def validate_file(path: Path, repo_root: Path) -> list[Issue]:
    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    try:
        with tokenize.open(path) as fh:
            source = fh.read()
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [Issue(rel, 1, 1, "read", str(exc))]
    return validate_source(source, rel)


def run_preflight(files: Iterable[Path], repo_root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for path in files:
        file_issues = validate_file(path, repo_root)
        if file_issues:
            issues.extend(file_issues)
        else:
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            print(f"[preflight] OK {rel}")
    return issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        help="Git ref/SHA to diff against. Local default is the configured upstream.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check every tracked/untracked Market Radar Python file.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root (mainly for tests). Defaults to the parent of market_radar/.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        base = None if args.all else resolve_base(repo_root, args.base)
        files = collect_python_files(repo_root, args.base, all_files=args.all)
    except RuntimeError as exc:
        print(f"[preflight] ERROR {exc}", file=sys.stderr)
        return 2

    scope = (
        "all Market Radar Python"
        if args.all
        else f"changed Market Radar Python (base={base or 'fallback-all'})"
    )
    print(f"[preflight] scope: {scope}")
    print(f"[preflight] files: {len(files)}")
    if not files:
        print("[preflight] no changed Market Radar Python files")
        return 0

    issues = run_preflight(files, repo_root)
    if not issues:
        print("[preflight] PASS")
        return 0

    for issue in issues:
        print(
            f"[preflight] ERROR {issue.path}:{issue.line}:{issue.column} "
            f"[{issue.kind}] {issue.message}",
            file=sys.stderr,
        )
    print(f"[preflight] FAIL ({len(issues)} issue(s))", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
