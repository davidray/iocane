"""These mock subprocess.run throughout - they must never shell out to a
real `lp`/`lpstat`, since that could actually queue a print job."""

import subprocess

import pytest

from netprint_mcp import cups


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_list_printers_parses_lpstat_output(monkeypatch):
    def fake_run(args, **_kwargs):
        assert args == ["lpstat", "-p"]
        return FakeCompletedProcess(
            stdout=(
                "printer HP_OfficeJet_Pro is idle.  enabled since Mon 01 Jan 2024\n"
                "printer Old_Inkjet is stopped.  enabled since Mon 01 Jan 2024\n"
            )
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cups.list_printers() == [
        {"name": "HP_OfficeJet_Pro", "status": "is idle"},
        {"name": "Old_Inkjet", "status": "is stopped"},
    ]


def test_list_printers_handles_non_is_phrasing(monkeypatch):
    # lpstat uses different wording for an actively-printing job - the
    # parser shouldn't require the literal word "is".
    def fake_run(args, **_kwargs):
        return FakeCompletedProcess(
            stdout="printer HP_OfficeJet_Pro now printing HP_OfficeJet_Pro-12.  enabled\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    printers = cups.list_printers()

    assert printers == [{"name": "HP_OfficeJet_Pro", "status": "now printing HP_OfficeJet_Pro-12"}]


def test_list_printers_empty_when_none_configured(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout=""))

    assert cups.list_printers() == []


def test_get_default_printer_parses_lpstat_d(monkeypatch):
    def fake_run(args, **_kwargs):
        assert args == ["lpstat", "-d"]
        return FakeCompletedProcess(stdout="system default destination: HP_OfficeJet_Pro\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cups.get_default_printer() == "HP_OfficeJet_Pro"


def test_get_default_printer_returns_none_when_unset(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="no system default destination\n")
    )

    assert cups.get_default_printer() is None


def test_print_document_builds_correct_lp_command(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("fake pdf content")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["lpstat", "-p"]:
            return FakeCompletedProcess(stdout="printer HP_OfficeJet_Pro is idle.\n")
        if args[0] == "lp":
            return FakeCompletedProcess(stdout="request id is HP_OfficeJet_Pro-1 (1 file(s))\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = cups.print_document(str(doc), printer="HP_OfficeJet_Pro")

    assert result == "request id is HP_OfficeJet_Pro-1 (1 file(s))"
    lp_call = next(c for c in calls if c[0] == "lp")
    assert lp_call == ["lp", "-d", "HP_OfficeJet_Pro", str(doc)]


def test_print_document_passes_copies_flag(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["lpstat", "-p"]:
            return FakeCompletedProcess(stdout="printer HP is idle.\n")
        return FakeCompletedProcess(stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    cups.print_document(str(doc), printer="HP", copies=3)

    lp_call = next(c for c in calls if c[0] == "lp")
    assert lp_call == ["lp", "-d", "HP", "-n", "3", str(doc)]


def test_print_document_uses_default_printer_when_none_named(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args == ["lpstat", "-d"]:
            return FakeCompletedProcess(stdout="system default destination: HP\n")
        if args[:2] == ["lpstat", "-p"]:
            return FakeCompletedProcess(stdout="printer HP is idle.\n")
        return FakeCompletedProcess(stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    cups.print_document(str(doc))

    lp_call = next(c for c in calls if c[0] == "lp")
    assert lp_call == ["lp", "-d", "HP", str(doc)]


def test_print_document_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        cups.print_document("/nonexistent/path.pdf", printer="HP")


def test_print_document_unknown_printer_raises(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")

    def fake_run(args, **_kwargs):
        if args[:2] == ["lpstat", "-p"]:
            return FakeCompletedProcess(stdout="printer HP is idle.\n")
        raise AssertionError("lp should not have been called for an unknown printer")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="Nonexistent"):
        cups.print_document(str(doc), printer="Nonexistent")


def test_print_document_no_printer_and_no_default_raises(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")

    def fake_run(args, **_kwargs):
        if args == ["lpstat", "-d"]:
            return FakeCompletedProcess(stdout="no system default destination\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="default"):
        cups.print_document(str(doc))


def test_print_document_lp_failure_raises_with_stderr(tmp_path, monkeypatch):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")

    def fake_run(args, **_kwargs):
        if args[:2] == ["lpstat", "-p"]:
            return FakeCompletedProcess(stdout="printer HP is idle.\n")
        if args[0] == "lp":
            return FakeCompletedProcess(stderr="lp: Unable to contact printer.\n", returncode=1)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Unable to contact printer"):
        cups.print_document(str(doc), printer="HP")


def test_print_document_rejects_invalid_copies(tmp_path):
    doc = tmp_path / "test.pdf"
    doc.write_text("x")

    with pytest.raises(ValueError, match="copies"):
        cups.print_document(str(doc), printer="HP", copies=0)


def test_missing_cups_binaries_raise_a_clear_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="not found"):
        cups.list_printers()
