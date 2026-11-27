"""The opt-in pytest report of committed ORM writes, including writes on plain sessions."""

from collections import Counter
from collections.abc import Generator

import pytest

from terp.core._write_journal import WriteJournal


class WriteReport(WriteJournal):
    def __init__(self) -> None:
        self.pending: list[list[str]] = []
        self.commits = 0
        self.reported: Counter[tuple[str, tuple[str, ...]]] = Counter()
        super().__init__(on_commit=self.pending.append)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        report = yield
        # TestReport properties travel to the controller when using pytest-xdist.
        report.user_properties.extend(("terp.write_commit", rows) for rows in self.pending)
        self.pending.clear()
        return report

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        for name, rows in report.user_properties:
            if name == "terp.write_commit":
                self.commits += 1
                if rows:
                    self.reported[report.nodeid, tuple(rows)] += 1

    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        flagged = self.reported.total()
        terminalreporter.write_sep("=", "terp write report")
        terminalreporter.write_line(
            f"{self.commits} ORM write transaction(s) committed, "
            f"{flagged} with changes outside an accepted write."
        )
        # Surface application models first even when frequently written framework tables
        # dominate the run. An application can itself write a framework model.
        for framework_only, heading in (
            (False, "Findings that include application models"),
            (True, "Findings on framework models only"),
        ):
            section = [
                (nodeid, rows, count) for (nodeid, rows), count in sorted(self.reported.items())
                if all(row.startswith(("terp.core.", "terp.capabilities.")) for row in rows)
                == framework_only
            ]
            if section:
                terminalreporter.write_line(heading)
                for nodeid, rows, count in section:
                    terminalreporter.write_line(f"  {nodeid} ({count}): {', '.join(rows)}")
