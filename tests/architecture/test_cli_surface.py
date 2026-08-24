"""``terp --help`` — the surface a person or an agent meets before any documentation.

The CLI is this framework's always-available answer to "what can I do here?". A user
who never installs anything beyond the framework has `--help`, `terp guide`, and the
app's own files; nothing else is guaranteed to exist. So two properties of the help
text are load-bearing enough to gate.

**Everything is listed.** ``argparse`` leaves a subparser out of the parent's listing
when it is registered without ``help=``. ``terp inspect`` was registered that way, so
five inspectors — the control plane, jobs, the access graph, the schema, capabilities
— did not appear in ``terp --help`` at all. They were reachable, documented in
``terp guide``, and invisible to anyone who started where people start.

**No help text names a product.** ``terp inspect access --format json`` is the seam
any consumer reads: an agent, a CI job, a dashboard. Three ``--format`` options
described it as "structured, for Studio", which tells everyone who is not running that
one product that the machine-readable mode is not for them — the exact inversion this
repository's layering is meant to prevent, since the framework is the core and any
tool on top of it is optional.

This is deliberately NOT the same rule as the repo-split gate's own
``test_the_framework_never_references_...`` check, which forbids the separately deployed
tool's DIRECTORY NAME anywhere in a framework source — a path breaks the moment the two
repositories split, and that gate is about coupling. A product name in an internal
docstring is neither coupling nor a promise to a user. A product name in ``--help`` is
what a user is told the tool is for, and that is what is gated here.

(That sibling gate matches the lowercase directory form, in any file under
``packages``/``tests``/``apps``/``template``. This module therefore never spells it, and
the check below matches case-insensitively from the capitalised product name so the
lowercase form does not have to be written down to be refused.)
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import pytest

# terp-cli is not pip-installed in the dev venv; inject its src (as test_cli_guide does).
_CLI_SRC = pathlib.Path(__file__).resolve().parents[2] / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import _build_parser  # noqa: E402  (import after sys.path setup)


def _subparser_actions(
    parser: argparse.ArgumentParser,
) -> list[argparse._SubParsersAction]:
    return [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]


def _walk(parser: argparse.ArgumentParser, path: str = "terp"):
    """Every parser in the tree, with the command path that reaches it."""
    yield path, parser
    for action in _subparser_actions(parser):
        for name, child in action.choices.items():
            yield from _walk(child, f"{path} {name}")


def _commands_missing_help(parser: argparse.ArgumentParser, path: str = "terp") -> list[str]:
    """Command paths registered without ``help=``, which argparse omits from listings."""
    missing: list[str] = []
    for action in _subparser_actions(parser):
        # `_ChoicesPseudoAction` is what argparse creates per registered subcommand, and
        # it exists ONLY when `help=` was passed. A name in `choices` with no matching
        # pseudo-action is a subcommand the parent's --help will not print.
        described = {pseudo.dest for pseudo in action._choices_actions}
        for name, child in action.choices.items():
            if name not in described:
                missing.append(f"{path} {name}")
            missing.extend(_commands_missing_help(child, f"{path} {name}"))
    return missing


def test_every_command_appears_in_its_parents_help() -> None:
    """A command argparse will not print is a command nobody finds.

    Mutation: drop the ``help=`` from any ``add_parser`` call and this names it.
    """
    assert _commands_missing_help(_build_parser()) == []


def test_the_command_tree_is_not_trivially_small() -> None:
    """The walk above must actually be walking something.

    A recursion that stopped finding subparsers would return an empty "missing" list
    and report green — the failure mode a completeness check cannot afford. Counted
    here rather than written into prose anywhere: this is the assertion, not a claim.
    """
    reachable = list(_walk(_build_parser()))
    assert len(reachable) > 30, f"only {len(reachable)} parsers reached; the walk is broken"


#: Products that may not be named in help text. Matched case-insensitively, which is
#: also how this module avoids writing the lowercase directory form the repo-split gate
#: refuses — see the note at the top.
_PRODUCT_NAMES = ("Studio",)


@pytest.mark.parametrize("product", _PRODUCT_NAMES)
def test_no_user_visible_help_names_a_product(product: str) -> None:
    """The framework is the core; a tool on top of it is optional and unnamed here.

    Covers every ``help=`` in the tree — the subcommand descriptions AND the option
    help — because both are printed to a user who may be running nothing but this.
    """
    needle = product.lower()
    offenders: list[str] = []
    for path, parser in _walk(_build_parser()):
        if parser.description and needle in parser.description.lower():
            offenders.append(f"{path} (description)")
        for action in parser._actions:
            if action.help and needle in action.help.lower():
                offenders.append(f"{path} {action.option_strings or action.dest}")
    assert offenders == [], (
        f"CLI help text names {product!r}: {offenders}. A machine-readable format is for "
        f"whoever is reading it; naming one product tells every other reader it is not "
        f"for them."
    )


def test_the_inspectors_are_all_described() -> None:
    """The specific regression: `terp inspect` and two of its five subcommands.

    Named rather than left to the generic check above, because this is the one that
    happened and the one worth recognising if it happens again.
    """
    parser = _build_parser()
    inspect = next(
        child
        for action in _subparser_actions(parser)
        for name, child in action.choices.items()
        if name == "inspect"
    )
    described = {
        pseudo.dest
        for action in _subparser_actions(inspect)
        for pseudo in action._choices_actions
    }
    assert described >= {"control-plane", "jobs", "access", "capabilities", "schema"}, (
        f"terp inspect --help does not describe {sorted({'control-plane', 'jobs', 'access', 'capabilities', 'schema'} - described)}"
    )


# --------------------------------------------------------------------------- #
# The index an agent reads before it reads anything else.
# --------------------------------------------------------------------------- #


def test_guide_lists_its_topics_without_prose(capsys: pytest.CaptureFixture[str]) -> None:
    """`terp guide --list` answers "what can I ask about?" as data.

    The overview advertises its topics in a wrapped English sentence, which is fine for
    a person and is a regex for everything else — and `check` and `verify` both already
    answer in JSON on request, so the one command an agent reaches for first was the
    odd one out.
    """
    from terp.cli import guide_topics, main

    main(["guide", "--list"])
    listed = capsys.readouterr().out.split()
    assert tuple(listed) == guide_topics()


def test_guide_lists_topics_and_rules_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Rules are a separate key, not folded in with the topics.

    `terp guide <name>` accepts both, but they answer different questions: a topic is a
    subject to learn, a rule is the remediation for one gate finding. A consumer asking
    "what can I read about?" wants the topics; a consumer holding a violation already
    has the rule name.
    """
    import json as _json

    from terp.cli import guide_choices, guide_topics, main

    main(["guide", "--list", "--format", "json"])
    payload = _json.loads(capsys.readouterr().out)
    assert payload["topics"] == list(guide_topics())
    assert set(payload["rules"]) == set(guide_choices()) - set(guide_topics())
    assert payload["rules"], "no architecture rules surfaced"
    assert not set(payload["rules"]) & set(payload["topics"])
