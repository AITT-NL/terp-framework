"""Pytest options and fixture for ORM write reporting and validation."""

from collections.abc import Iterator
from contextlib import closing

import pytest


_WRITE_REPORT_FLAG = "--terp-report-writes"
_WRITE_VALIDATION_FLAG = "--terp-validate-writes"


def add_write_options(parser: pytest.Parser) -> None:
    parser.addoption(
        _WRITE_REPORT_FLAG, action="store_true",
        help="Report committed ORM rows and columns changed outside an accepted service or infrastructure write.",
    )
    parser.addoption(
        _WRITE_VALIDATION_FLAG, action="store_true",
        help="Refuse ORM commits with changes outside an accepted service or infrastructure write.",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption(_WRITE_REPORT_FLAG):
        from terp.core._write_report import WriteReport

        report = WriteReport()
        config.pluginmanager.register(report)
        config.add_cleanup(report.close)
    if config.getoption(_WRITE_VALIDATION_FLAG):
        from terp.core._commit_validation import CommitValidation

        config.add_cleanup(CommitValidation().close)


@pytest.fixture
def terp_validate_writes(pytestconfig: pytest.Config) -> Iterator[None]:
    """Enable commit validation for this test, including its dependent fixtures."""
    if pytestconfig.getoption(_WRITE_VALIDATION_FLAG):
        yield
    else:
        from terp.core._commit_validation import CommitValidation

        with closing(CommitValidation()):
            yield
