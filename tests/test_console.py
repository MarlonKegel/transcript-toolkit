"""The full-run gate: confirm the spend and pick the transport in one prompt."""
import pytest

import transcript_toolkit.core.console as console
from transcript_toolkit.core.console import choose_transport
from transcript_toolkit.errors import ToolkitError

EST = (3.20, 1.60)          # (standard_usd, batch_usd)


@pytest.fixture
def tty(monkeypatch):
    """Pretend we're interactive; feed canned answers to input() and record its prompt (the y/N
    path writes its text as the input prompt, not to stdout, so capsys alone can't see it)."""
    monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("TOOLKIT_YES", raising=False)
    prompts: list[str] = []

    def answer(text):
        monkeypatch.setattr("builtins.input", lambda prompt="": (prompts.append(prompt), text)[1])
        return prompts
    answer.prompts = prompts
    return answer


def test_menu_picks_synchronous(tty, capsys):
    tty("1")
    assert choose_transport("Tag 801 clip(s).", EST) is False
    out = capsys.readouterr().out
    assert "~$3.20" in out and "~$1.60" in out          # both estimates shown
    assert "24h" in out                                 # turnaround stated up front


def test_menu_picks_batch(tty):
    tty("2")
    assert choose_transport("Tag 801 clip(s).", EST) is True


@pytest.mark.parametrize("reply", ["n", "", "q"])
def test_menu_cancel_aborts(tty, reply):
    tty(reply)
    with pytest.raises(ToolkitError, match="Aborted"):
        choose_transport("Tag 801 clip(s).", EST)


def test_missing_estimate_is_not_guessed(tty, capsys):
    tty("1")
    choose_transport("Tag 801 clip(s).", None)
    out = capsys.readouterr().out
    assert "cost unknown" in out
    assert "$" not in out                               # never invent a figure


def test_explicit_flag_downgrades_to_spend_confirm(tty, capsys):
    """--batch/--no-batch fixes the transport; the user still confirms the money."""
    prompts = tty("y")
    assert choose_transport("Tag 801 clip(s).", EST, batch=True) is True
    assert "[1]" not in capsys.readouterr().out         # no menu printed
    assert "[y/N]" in prompts[-1] and "~$1.60" in prompts[-1]   # batch price, not the standard one

    prompts = tty("n")
    with pytest.raises(ToolkitError, match="Aborted"):
        choose_transport("Tag 801 clip(s).", EST, batch=False)
    assert "~$3.20" in prompts[-1]                      # --no-batch quotes the standard price


def test_yes_skips_prompt_and_honours_flag(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p="": pytest.fail("must not prompt"))
    assert choose_transport("x", EST, yes=True) is False            # default: run now
    assert choose_transport("x", EST, yes=True, batch=True) is True


def test_toolkit_yes_env_skips_prompt(monkeypatch):
    monkeypatch.setenv("TOOLKIT_YES", "1")
    monkeypatch.setattr("builtins.input", lambda _p="": pytest.fail("must not prompt"))
    assert choose_transport("x", EST) is False


def test_non_interactive_without_yes_refuses(monkeypatch):
    monkeypatch.setattr(console.sys.stdin, "isatty", lambda: False)
    monkeypatch.delenv("TOOLKIT_YES", raising=False)
    with pytest.raises(ToolkitError, match="non-interactively without --yes"):
        choose_transport("x", EST)
