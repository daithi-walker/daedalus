from pathlib import Path

import pytest

from src.ticket import find_ticket, load_ticket, build_goal, check_quality, Ticket


@pytest.fixture
def backlog_ticket(tmp_path: Path) -> Path:
    p = tmp_path / "backlog-item.md"
    p.write_text(
        "---\n"
        "title: Backlog Item\n"
        "state: To Do\n"
        "repo: my-repo\n"
        "---\n"
        "\n"
        "## Summary\n"
        "\n"
        "This is a summary with more than ten words to satisfy the quality check.\n"
        "\n"
        "## Acceptance Criteria\n"
        "\n"
        "- [ ] First acceptance criterion is met\n"
        "- [ ] Second acceptance criterion is met\n"
    )
    return p


@pytest.fixture
def ado_ticket(tmp_path: Path) -> Path:
    p = tmp_path / "ado-item.md"
    p.write_text(
        "---\n"
        "title: Backlog Item\n"
        "state: To Do\n"
        "repo: my-repo\n"
        "ado_id: '42'\n"
        "---\n"
        "\n"
        "## Summary\n"
        "\n"
        "This is a summary with more than ten words to satisfy the quality check.\n"
        "\n"
        "## Acceptance Criteria\n"
        "\n"
        "- [ ] First acceptance criterion is met\n"
        "- [ ] Second acceptance criterion is met\n"
    )
    return p


def test_find_ticket_direct_md_exists(tmp_path: Path, backlog_ticket: Path) -> None:
    result = find_ticket(tmp_path, str(backlog_ticket))
    assert result == backlog_ticket


def test_find_ticket_relative_bare_filename(tmp_path: Path, backlog_ticket: Path) -> None:
    result = find_ticket(tmp_path, "backlog-item.md")
    assert result == backlog_ticket.resolve()


def test_find_ticket_direct_md_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_ticket(tmp_path, str(tmp_path / "nonexistent.md"))


@pytest.mark.parametrize(
    "ado_id, expected_in, expected_not_in",
    [
        ("", None, "(ADO #)"),
        ("42", "(ADO #42)", None),
    ],
)
def test_build_goal_ado_id_variants(
    tmp_path: Path, ado_id: str, expected_in: str | None, expected_not_in: str | None
) -> None:
    ticket = Ticket(
        ado_id=ado_id,
        title="My Ticket",
        state="To Do",
        summary="A short summary.",
        acceptance_criteria=["Criterion one", "Criterion two"],
        plan=[],
        path=tmp_path / "ticket.md",
        repo="my-repo",
    )
    first_line = build_goal(ticket).splitlines()[0]
    if expected_in:
        assert expected_in in first_line, first_line
    if expected_not_in:
        assert expected_not_in not in first_line, first_line


def test_check_quality_valid_backlog_ticket(backlog_ticket: Path) -> None:
    ticket = load_ticket(backlog_ticket)
    result = check_quality(ticket)
    assert result.passed is True
    assert result.errors == []


def test_load_ticket_backlog_format(backlog_ticket: Path) -> None:
    ticket = load_ticket(backlog_ticket)
    assert ticket.ado_id == ""
    assert ticket.title == "Backlog Item"
    assert ticket.state == "To Do"
    assert ticket.repo == "my-repo"


def test_load_ticket_ado_format(ado_ticket: Path) -> None:
    ticket = load_ticket(ado_ticket)
    assert ticket.ado_id == '42'


def _write_ticket(tmp_path: Path, content: str, name: str = "123-test.md") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


MINIMAL_TICKET = """\
---
ado_id: 123
title: Refactor pipeline scripts
state: To Do
---

## Summary

Refactor the pipeline module to separate transformation logic from
orchestration, making each script independently testable.

## Acceptance Criteria

- [ ] Each pipeline stage lives in its own module
- [ ] All modules have unit tests with ≥80% coverage
- [ ] No shared mutable state between stages

## Plan

- Extract transformation functions into pipeline/transforms.py
- Update imports across pipeline scripts
"""


class TestLoadTicket:
    def test_loads_ado_id(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert t.ado_id == "123"

    def test_loads_title(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert t.title == "Refactor pipeline scripts"

    def test_loads_state(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert t.state == "To Do"

    def test_loads_summary(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert "transformation logic" in t.summary

    def test_loads_acceptance_criteria(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert len(t.acceptance_criteria) == 3
        assert t.acceptance_criteria[0] == "Each pipeline stage lives in its own module"

    def test_strips_checkbox_markers(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        for c in t.acceptance_criteria:
            assert not c.startswith("[ ]")
            assert not c.startswith("[x]")
            assert not c.startswith("⬜")
            assert not c.startswith("✅")

    def test_loads_plan(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert len(t.plan) == 2
        assert "transforms.py" in t.plan[0]

    def test_missing_frontmatter_uses_stem_as_title(self, tmp_path):
        content = "## Summary\n\nJust a summary with enough words here to pass the check.\n"
        p = _write_ticket(tmp_path, content, name="1999-fallback.md")
        t = load_ticket(p)
        assert t.title == "1999-fallback"
        assert t.ado_id == ""

    def test_ticket_path_stored(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        assert t.path == p


class TestCheckQuality:
    def test_passes_for_valid_ticket(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        result = check_quality(t)
        assert result.passed
        assert not result.errors

    def test_fails_for_missing_summary(self, tmp_path):
        content = MINIMAL_TICKET.replace("## Summary\n\nRefactor the pipeline module to separate transformation logic from\norchestration, making each script independently testable.\n", "## Summary\n\nShort.\n")
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert not result.passed
        assert any("Summary" in e for e in result.errors)

    def test_fails_for_no_acceptance_criteria(self, tmp_path):
        content = MINIMAL_TICKET.replace("## Acceptance Criteria\n\n- [ ] Each pipeline stage lives in its own module\n- [ ] All modules have unit tests with ≥80% coverage\n- [ ] No shared mutable state between stages\n", "")
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert not result.passed
        assert any("acceptance" in e.lower() for e in result.errors)

    def test_fails_for_single_criterion(self, tmp_path):
        content = """\
---
ado_id: 123
title: Test
state: To Do
---

## Summary

This summary has enough words to pass the minimum length check for quality.

## Acceptance Criteria

- [ ] Only one criterion here
"""
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert not result.passed
        assert any("1 acceptance criterion" in e for e in result.errors)

    def test_fails_for_vague_criteria(self, tmp_path):
        content = """\
---
ado_id: 123
title: Test
state: To Do
---

## Summary

This summary has enough words to pass the minimum length check for quality gate.

## Acceptance Criteria

- [ ] First criterion is fine and complete
- [ ] Second criterion is TBD
"""
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert not result.passed
        assert any("Vague" in e for e in result.errors)

    def test_fails_for_done_state(self, tmp_path):
        content = MINIMAL_TICKET.replace("state: To Do", "state: Done")
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert not result.passed
        assert any("Done" in e for e in result.errors)

    def test_warns_for_missing_plan(self, tmp_path):
        content = """\
---
ado_id: 123
title: Test
state: To Do
---

## Summary

This summary has enough words to pass the minimum length check for quality gate.

## Acceptance Criteria

- [ ] First criterion is fine and complete
- [ ] Second criterion is also complete and fine
"""
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        assert result.passed
        assert any("Plan" in w for w in result.warnings)

    def test_report_includes_errors_and_warnings(self, tmp_path):
        content = MINIMAL_TICKET.replace("state: To Do", "state: Done")
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        result = check_quality(t)
        report = result.report()
        assert "✗" in report


class TestBuildGoal:
    def test_includes_title_and_ado_id(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        goal = build_goal(t)
        assert "Refactor pipeline scripts" in goal
        assert "ADO #123" in goal

    def test_includes_summary(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        goal = build_goal(t)
        assert "transformation logic" in goal

    def test_includes_acceptance_criteria(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        goal = build_goal(t)
        assert "Acceptance criteria:" in goal
        assert "- Each pipeline stage lives in its own module" in goal

    def test_includes_plan_as_implementation_notes(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET)
        t = load_ticket(p)
        goal = build_goal(t)
        assert "Implementation notes:" in goal
        assert "transforms.py" in goal

    def test_omits_plan_section_when_empty(self, tmp_path):
        content = """\
---
ado_id: 123
title: Test
state: To Do
---

## Summary

This summary has enough words to pass the minimum length check for quality gate.

## Acceptance Criteria

- [ ] First criterion
- [ ] Second criterion
"""
        p = _write_ticket(tmp_path, content)
        t = load_ticket(p)
        goal = build_goal(t)
        assert "Implementation notes:" not in goal


class TestFindTicket:
    def test_finds_by_filename_prefix(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET, "123-refactor.md")
        found = find_ticket(tmp_path, "123")
        assert found == p

    def test_finds_by_frontmatter_ado_id(self, tmp_path):
        p = _write_ticket(tmp_path, MINIMAL_TICKET, "refactor-work.md")
        found = find_ticket(tmp_path, "123")
        assert found == p

    def test_raises_when_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_ticket(tmp_path, "9999")

    def test_skips_underscore_files(self, tmp_path):
        _write_ticket(tmp_path, MINIMAL_TICKET, "_template.md")
        with pytest.raises(FileNotFoundError):
            find_ticket(tmp_path, "9999")
