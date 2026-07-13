"""Load, validate, and convert ticket markdown files into Daedalus workflow goals.

Issue files use the knowledge-repo format:
  - YAML frontmatter: ado_id, title, state, tags, ...
  - ## Summary
  - ## Acceptance Criteria   (checkbox list)
  - ## Plan                  (bullet list)
  - ## Reference             (optional)
"""

import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Ticket:
    ado_id: str
    title: str
    state: str
    summary: str
    acceptance_criteria: list[str]
    plan: list[str]
    path: Path
    repo: str = ""  # alias or URL from frontmatter `repo:` field


@dataclass
class QualityResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = []
        for e in self.errors:
            lines.append(f"  ✗  {e}")
        for w in self.warnings:
            lines.append(f"  ⚠  {w}")
        return "\n".join(lines)


def load_ticket(path: Path) -> Ticket:
    text = path.read_text()

    # Parse YAML frontmatter
    fm: dict = {}
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if fm_match:
        fm = yaml.safe_load(fm_match.group(1)) or {}
        text = text[fm_match.end():]

    def _extract_section(name: str) -> str:
        pattern = rf"##\s+{re.escape(name)}\s*\n(.*?)(?=\n##\s|\Z)"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    summary = _extract_section("Summary")
    ac_raw = _extract_section("Acceptance Criteria")
    plan_raw = _extract_section("Plan")

    acceptance_criteria = [
        re.sub(r"^[-*]\s*[⬜✅☑]\s*|^[-*]\s*\[[ x]\]\s*|^[-*]\s*", "", line).strip()
        for line in ac_raw.splitlines()
        if line.strip() and re.match(r"^\s*[-*]", line)
    ]

    plan = [
        re.sub(r"^[-*]\s*", "", line).strip()
        for line in plan_raw.splitlines()
        if line.strip() and re.match(r"^\s*[-*]", line)
    ]

    return Ticket(
        ado_id=str(fm.get("ado_id", "")),
        title=str(fm.get("title", path.stem)),
        state=str(fm.get("state", "")),
        summary=summary,
        acceptance_criteria=acceptance_criteria,
        plan=plan,
        path=path,
        repo=str(fm.get("repo", "")),
    )


def check_quality(ticket: Ticket) -> QualityResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not ticket.summary or len(ticket.summary.split()) < 10:
        errors.append("Summary is missing or too short (< 10 words)")

    if not ticket.acceptance_criteria:
        errors.append("No acceptance criteria found")
    elif len(ticket.acceptance_criteria) < 2:
        errors.append(f"Only {len(ticket.acceptance_criteria)} acceptance criterion - need at least 2")

    vague = [c for c in ticket.acceptance_criteria
             if re.search(r"\b(tbd|todo|tbc|placeholder|fixme)\b", c, re.IGNORECASE)]
    if vague:
        errors.append(f"Vague/incomplete criteria: {vague}")

    if not ticket.plan:
        warnings.append("No Plan section - planner agent will work from acceptance criteria only")
    elif len(ticket.plan) < 2:
        warnings.append("Plan has only 1 bullet - consider expanding for better planner guidance")

    if ticket.state.lower() in ("done", "closed", "resolved", "removed"):
        errors.append(f"Ticket state is '{ticket.state}' - this work may already be complete")

    return QualityResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def build_goal(ticket: Ticket) -> str:
    ref = f" (ADO #{ticket.ado_id})" if ticket.ado_id else ""
    parts = [f"{ticket.title}{ref}", ""]

    parts += [ticket.summary, ""]

    if ticket.acceptance_criteria:
        parts.append("Acceptance criteria:")
        for c in ticket.acceptance_criteria:
            parts.append(f"- {c}")
        parts.append("")

    if ticket.plan:
        parts.append("Implementation notes:")
        for p in ticket.plan:
            parts.append(f"- {p}")

    return "\n".join(parts).strip()


def find_ticket(tickets_dir: Path, ticket_id: str) -> Path:
    """Find a ticket file.

    If ticket_id is a path to an existing .md file, return it directly.
    Otherwise search tickets_dir by ADO ID prefix (NNN-*.md) or frontmatter.
    """
    # Direct path: caller passed backlog/foo.md or an absolute path
    candidate = Path(ticket_id).expanduser()
    if candidate.suffix == ".md":
        if not candidate.is_absolute() and tickets_dir is not None:
            relative = (tickets_dir / ticket_id).expanduser()
            if relative.is_file():
                return relative.resolve()
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"Ticket file not found: {ticket_id}")
    if tickets_dir is not None:
        matches = list(tickets_dir.glob(f"{ticket_id}-*.md"))
        if not matches:
            # Also search by ado_id in frontmatter as fallback
            for f in tickets_dir.glob("*.md"):
                if f.name.startswith("_"):
                    continue
                text = f.read_text()
                if re.search(rf"^ado_id:\s*{re.escape(ticket_id)}\s*$", text, re.MULTILINE):
                    return f
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"No ticket file found for ID {ticket_id}"
        + (f" in {tickets_dir}" if tickets_dir else "")
    )
