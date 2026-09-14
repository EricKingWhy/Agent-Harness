#!/usr/bin/env python3
"""Pull GitHub issues into a local read-only snapshot.

GitHub Issues remain the single source of truth (see
``docs/agents/issue-tracker.md``). This script only *reads* via the ``gh``
CLI and writes a deterministic snapshot under ``docs/tickets/`` so that
agents and humans can browse tickets offline.

Outputs:
    docs/tickets/README.md      index table (sorted by number)
    docs/tickets/NN-<slug>.md   one file per issue, body verbatim
    docs/tickets/tickets.json   raw JSON dump for programmatic access

Usage:
    python scripts/snapshot_tickets.py [--repo OWNER/NAME] [--state all|open|closed]

Exit codes:
    0  success
    1  ``gh`` not available or repo resolution failed
    2  ``gh`` returned an error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "tickets"
INDEX_MD = OUT_DIR / "README.md"
JSON_OUT = OUT_DIR / "tickets.json"

# GitHub label colours vary; we just need the name for the snapshot.
LIST_FIELDS = "number,title,state,labels,assignees"
VIEW_FIELDS = "number,title,state,labels,assignees,author,createdAt,closedAt,body"


def die(msg: str, code: int) -> None:
    print(f"snapshot_tickets: {msg}", file=sys.stderr)
    raise SystemExit(code)


def gh(args: list[str]) -> str:
    cmd = ["gh", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        die("`gh` CLI not found on PATH — install it and run `gh auth login`.", 1)
    if result.returncode != 0:
        die(f"`{' '.join(cmd)}` failed:\n{result.stderr.strip()}", 2)
    return result.stdout


def slugify(title: str) -> str:
    """Stable, filesystem-safe slug. ASCII-only, lowercase, dashed."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return s or "ticket"


def parse_relationships(body: str | None) -> tuple[list[int], list[int]]:
    """Best-effort scrape of parent/blocked-by from issue body.

    Matt's /to-tickets writes `## Parent\n#N — ...` and
    `## Blocked by\n#N` sections; we mirror that loosely so the index
    can hint at structure without claiming completeness.
    """
    body = body or ""
    parents: list[int] = []
    blockers: list[int] = []

    parent_match = re.search(r"^##\s*Parent\s*$", body, re.MULTILINE)
    if parent_match:
        section = body[parent_match.end():]
        # Stop at next markdown heading.
        section = re.split(r"^##\s", section, maxsplit=1, flags=re.MULTILINE)[0]
        parents = [int(n) for n in re.findall(r"#(\d+)", section)]

    blocked_match = re.search(r"^##\s*Blocked\s*by\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not blocked_match:
        blocked_match = re.search(r"^Blocked\s*by:\s*(.+)$", body, re.MULTILINE)
        if blocked_match:
            blockers = [int(n) for n in re.findall(r"#?(\d+)", blocked_match.group(1))]
    else:
        section = body[blocked_match.end():]
        section = re.split(r"^##\s", section, maxsplit=1, flags=re.MULTILINE)[0]
        blockers = [int(n) for n in re.findall(r"#(\d+)", section)]

    return parents, blockers


def render_ticket_md(issue: dict) -> str:
    number = issue["number"]
    title = issue["title"]
    state = issue["state"]
    labels = ", ".join(l["name"] for l in issue.get("labels", [])) or "—"
    assignees = ", ".join(a["login"] for a in issue.get("assignees", [])) or "unassigned"
    author = issue.get("author", {}) or {}
    author_login = author.get("login", "unknown") if isinstance(author, dict) else "unknown"
    created = issue.get("createdAt", "")
    closed = issue.get("closedAt") or "—"
    body = issue.get("body") or "_(no body)_"
    parents, blockers = parse_relationships(issue.get("body"))

    header = [
        f"# #{number} — {title}",
        "",
        "> **Snapshot.** GitHub is the single source of truth.",
        "> Refresh with `python scripts/snapshot_tickets.py`.",
        "",
        f"- **State**: {state}",
        f"- **Labels**: {labels}",
        f"- **Assignees**: {assignees}",
        f"- **Author**: {author_login}",
        f"- **Created**: {created}",
        f"- **Closed**: {closed}",
    ]
    if parents:
        header.append(f"- **Parent**: {', '.join(f'#{n}' for n in parents)}")
    if blockers:
        header.append(f"- **Blocked by**: {', '.join(f'#{n}' for n in blockers)}")
    header += [
        f"- **GitHub**: {issue_url(number)}",
        "",
        "---",
        "",
        body,
        "",
    ]
    return "\n".join(header)


def issue_url(number: int) -> str:
    repo = resolve_repo()
    return f"https://github.com/{repo}/issues/{number}" if repo else f"# issue {number}"


def resolve_repo() -> str:
    """Return 'OWNER/NAME' via `gh repo view`, or '' if it can't be resolved.

    `gh repo view` resolves the repo from the git remote of the cwd, so this
    works without a global config key.
    """
    try:
        out = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    except SystemExit:
        return ""
    return out.strip()


def render_index(rows: list[dict], fetched_at: datetime) -> str:
    by_state = {"OPEN": [], "CLOSED": []}
    for r in rows:
        by_state.get(r["state"], by_state["OPEN"]).append(r)

    lines = [
        "# Ticket snapshot",
        "",
        (
            f"> Auto-generated by `scripts/snapshot_tickets.py` at "
            f"{fetched_at.isoformat(timespec='seconds')}."
        ),
        (
            "> GitHub Issues remain the single source of truth — "
            "this file is a read-only mirror. Re-run the script to refresh."
        ),
        "",
        (
            f"Total: **{len(rows)}** (open: {len(by_state['OPEN'])}, "
            f"closed: {len(by_state['CLOSED'])})."
        ),
        "",
        "| # | Title | State | Labels | Blocked by | File |",
        "|---|---|---|---|---|---|",
    ]

    for r in sorted(rows, key=lambda x: x["number"]):
        labels = ", ".join(r["labels"]) or "—"
        blocked = ", ".join(f"#{n}" for n in r["blockers"]) or "—"
        lines.append(
            f"| {r['number']} | {r['title']} | {r['state']} | "
            f"{labels} | {blocked} | [{r['filename']}]({r['filename']}) |"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="OWNER/NAME override; defaults to `gh` resolution")
    parser.add_argument(
        "--state",
        choices=("all", "open", "closed"),
        default="all",
        help="which issues to fetch (default: all)",
    )
    parser.add_argument(
        "--limit", type=int, default=1000, help="max issues to fetch (default 1000)"
    )
    args = parser.parse_args()

    list_args = [
        "issue", "list",
        "--state", args.state,
        "--limit", str(args.limit),
        "--json", LIST_FIELDS,
    ]
    if args.repo:
        list_args += ["--repo", args.repo]

    raw = gh(list_args)
    summary = json.loads(raw)
    if not summary:
        print(f"snapshot_tickets: no issues found (state={args.state}).")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        return

    # Fetch full body for each issue.
    view_args_base = ["issue", "view"]
    if args.repo:
        view_args_base += ["--repo", args.repo]

    full: list[dict] = []
    for entry in sorted(summary, key=lambda x: x["number"]):
        number = entry["number"]
        out = gh(view_args_base + [str(number), "--json", VIEW_FIELDS])
        full.append(json.loads(out))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe stale per-ticket files so deletions on GitHub are reflected.
    for old in OUT_DIR.glob("[0-9]*.md"):
        old.unlink()

    rows: list[dict] = []
    for issue in full:
        number = issue["number"]
        slug = slugify(issue["title"])
        filename = f"{number:02d}-{slug}.md"
        (OUT_DIR / filename).write_text(render_ticket_md(issue), encoding="utf-8")
        parents, blockers = parse_relationships(issue.get("body"))
        rows.append({
            "number": number,
            "title": issue["title"],
            "state": issue["state"],
            "labels": [l["name"] for l in issue.get("labels", [])],
            "parents": parents,
            "blockers": blockers,
            "filename": filename,
        })

    fetched_at = datetime.now(UTC)
    INDEX_MD.write_text(render_index(rows, fetched_at), encoding="utf-8")
    JSON_OUT.write_text(
        json.dumps({"fetched_at": fetched_at.isoformat(), "issues": full}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        f"snapshot_tickets: wrote {len(rows)} tickets to {OUT_DIR.relative_to(REPO_ROOT)}/ "
        f"(index: {INDEX_MD.name}, json: {JSON_OUT.name})."
    )


if __name__ == "__main__":
    main()
