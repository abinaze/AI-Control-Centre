"""Tests for checking the syntax of the Python files in a project."""

import contextlib
import os
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from aic_control_centre.execution import check_python as check_module
from aic_control_centre.execution.check_python import (
    ERRORS_SHOWN,
    FileTooLarge,
    LimitReached,
    NotRegularFile,
    Report,
    SyntaxProblem,
    check_directory,
    compile_problem,
    describe,
    python_version,
    read_python_file,
)

FAULTY = {
    "return outside a function": "return 1\n",
    "nonlocal at module level": "nonlocal x\n",
    "break outside a loop": "break\n",
    "duplicate argument": "def f(a, a):\n    pass\n",
    "await outside a function": "await x\n",
    "assignment to a literal": "1 = x\n",
    "unclosed bracket": "x = (\n",
    "python 2 print": "print 'hi'\n",
    "mixed tabs": "if 1:\n\tx = 1\n        y = 2\n",
}

FINE = {
    "empty": b"",
    "no final newline": b"x = 1",
    "windows line ends": b"x = 1\r\ny = 2\r\n",
    "byte order mark": b"\xef\xbb\xbfx = 1\n",
    "latin-1 comment": b"# -*- coding: latin-1 -*-\nx = '\xe9'\n",
    "a class": b"class A:\n    def f(self):\n        return 1\n",
}


def _write(root, name, data="x = 1\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, str):
        data = data.encode("utf-8")

    path.write_bytes(data)

    return path


def _listing(root):
    return sorted(
        (
            path.relative_to(root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in root.rglob("*")
    )


@contextlib.contextmanager
def _linked(link, target):
    """Make a link, a junction on Windows, and always remove it again."""
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        os.symlink(target, link)

    try:
        yield
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)


class _Scan:
    """What os.scandir returns, with entries made by a test."""

    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        return False

    def __iter__(self):
        return iter(self.entries)


def _entry(name, path, info=None):
    """An entry whose status is info, or cannot be read when info is None."""

    def status(follow_symlinks=True):
        if info is None:
            raise PermissionError("denied")

        return info

    return SimpleNamespace(name=name, path=path, stat=status)


def _info(mode, size=7, **fields):
    return SimpleNamespace(st_mode=mode, st_size=size, **fields)


def _fake_listing(monkeypatch, root, entries):
    """Make os.scandir return these entries for the top directory only.

    Any other directory is empty, so a mistake cannot loop for ever.
    """

    def scandir(path):
        if os.fspath(path) == os.fspath(root):
            return _Scan(entries)

        return _Scan([])

    monkeypatch.setattr(os, "scandir", scandir)


def _unexpected(path):
    raise AssertionError("a file was read: " + str(path))


def test_the_limits_are_the_ones_in_the_design() -> None:
    """The numbers are named constants, and these are their values."""
    assert check_module.MAX_FILE_BYTES == 1024 * 1024
    assert check_module.MAX_FILES == 10000
    assert check_module.MAX_TOTAL_BYTES == 64 * 1024 * 1024
    assert check_module.ERRORS_SHOWN == 3
    assert check_module.MESSAGE_LIMIT == 60


def test_source_that_is_valid_has_no_problem() -> None:
    """Every kind of valid file gives no problem."""
    for label, data in FINE.items():
        assert compile_problem("a.py", data) is None, label


def test_every_kind_of_faulty_source_is_a_problem() -> None:
    """The compiler finds more than the parser does, and all are caught."""
    missed = [
        label
        for label, source in FAULTY.items()
        if compile_problem("a.py", source.encode("utf-8")) is None
    ]

    assert missed == []


def test_a_problem_names_the_file_and_the_line() -> None:
    """The name is the one given, and the line is where it went wrong."""
    problem = compile_problem("pkg/a.py", b"x = 1\ny = (\n")

    assert problem.name == "pkg/a.py"
    assert problem.line == 1 or problem.line == 2
    assert problem.message


def test_source_that_cannot_be_decoded_is_a_problem() -> None:
    """A null byte, text that is not UTF-8, and an unknown encoding."""
    cases = [
        b"x = 1\x00\n",
        b"x = '\xff'\n",
        b"# coding: nosuchencoding\nx = 1\n",
    ]

    for data in cases:
        problem = compile_problem("a.py", data)

        assert problem is not None
        assert problem.message
        assert problem.line is None or problem.line >= 1


def test_very_deep_source_is_not_a_crash() -> None:
    """The compiler may refuse it or accept it, and the run goes on."""
    for data in (b"-" * 20000 + b"1", b"+".join([b"1"] * 200000)):
        problem = compile_problem("a.py", data)

        assert problem is None or problem.message


def test_every_exception_of_the_compiler_is_a_problem(monkeypatch) -> None:
    """A MemoryError or a RecursionError is a problem with the file."""
    for error in (
        MemoryError(),
        RecursionError("too deep"),
        ValueError("embedded null byte"),
        OverflowError("too big"),
    ):

        def refuse(*arguments, error=error, **keywords):
            raise error

        monkeypatch.setattr(check_module, "compile", refuse, raising=False)

        problem = compile_problem("a.py", b"x = 1\n")

        assert problem is not None
        assert problem.message == (str(error) or type(error).__name__)
        assert problem.line is None


def test_the_compiler_gets_a_fixed_name_and_no_inherited_flags(
    monkeypatch,
) -> None:
    """No text from the project is used to build anything."""
    calls = []

    def record(*arguments, **keywords):
        calls.append((arguments, keywords))

    monkeypatch.setattr(check_module, "compile", record, raising=False)

    assert compile_problem("some/evil\nname.py", b"x = 1\n") is None
    assert calls == [
        ((b"x = 1\n", "<file>", "exec"), {"dont_inherit": True}),
    ]


def test_an_interrupt_is_not_a_problem(monkeypatch) -> None:
    """Only exceptions are problems, so Ctrl-C still stops the run."""

    def interrupt(*arguments, **keywords):
        raise KeyboardInterrupt()

    monkeypatch.setattr(check_module, "compile", interrupt, raising=False)

    with pytest.raises(KeyboardInterrupt):
        compile_problem("a.py", b"x = 1\n")


def test_source_is_compiled_and_never_run(tmp_path) -> None:
    """A module that would write a file and exit does neither."""
    marker = tmp_path / "marker"
    source = (
        f"open({str(marker)!r}, 'w').write('ran')\n"
        "raise SystemExit(3)\n"
    )

    assert compile_problem("a.py", source.encode("utf-8")) is None
    assert not marker.exists()


def test_the_line_is_only_a_real_line_of_the_file() -> None:
    """No line, line 0 and a line that is not a number all give None."""
    line_of = check_module._line_of

    assert line_of(SyntaxError("m", ("f", 7, 1, "t"))) == 7
    assert line_of(SyntaxError("m", ("f", 0, 0, "t"))) is None
    assert line_of(SyntaxError("m")) is None
    assert line_of(ValueError("m")) is None
    assert line_of(SimpleNamespace(lineno="3")) is None


def test_the_text_of_an_error_falls_back_to_its_type() -> None:
    """An error with no text of its own is named by its type."""
    message_of = check_module._message_of

    assert message_of(SyntaxError("bad", ("f", 1, 1, "t"))) == "bad"
    assert message_of(ValueError("odd")) == "odd"
    assert message_of(MemoryError()) == "MemoryError"
    assert message_of(SyntaxError()) == "SyntaxError"
    assert message_of(SyntaxError("")) == "SyntaxError"
    assert message_of(TabError()) == "TabError"


def test_a_file_is_read_as_the_bytes_that_it_holds(tmp_path) -> None:
    """No line end is changed and no byte ends the file early."""
    data = b"x = 1\r\n\x1a\r\ny = 2\n"
    path = _write(tmp_path, "a.py", data)

    assert read_python_file(str(path)) == data
    assert read_python_file(str(_write(tmp_path, "b.py", b""))) == b""


def test_a_file_at_the_size_limit_is_read(tmp_path, monkeypatch) -> None:
    """The limit is on the size, and a file of exactly that size is read."""
    monkeypatch.setattr(check_module, "MAX_FILE_BYTES", 10)

    assert read_python_file(str(_write(tmp_path, "a.py", b"a" * 10)))

    with pytest.raises(FileTooLarge):
        read_python_file(str(_write(tmp_path, "b.py", b"a" * 11)))


def test_a_file_that_grew_is_not_read_whole(tmp_path, monkeypatch) -> None:
    """The size at the open is not trusted, so the reading is limited."""
    monkeypatch.setattr(check_module, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(
        check_module,
        "_status_of",
        lambda descriptor: _info(stat.S_IFREG | 0o644, 1),
    )
    path = _write(tmp_path, "a.py", b"a" * 50)

    with pytest.raises(FileTooLarge):
        read_python_file(str(path))


def test_what_is_not_a_regular_file_is_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The kind is that of the open descriptor, whatever the name was."""
    monkeypatch.setattr(
        check_module,
        "_status_of",
        lambda descriptor: _info(stat.S_IFIFO | 0o644),
    )
    path = _write(tmp_path, "a.py")

    with pytest.raises(NotRegularFile) as caught:
        read_python_file(str(path))

    assert isinstance(caught.value, OSError)


def test_a_file_known_to_be_too_large_is_not_read_at_all(
    tmp_path,
    monkeypatch,
) -> None:
    """The size at the open is enough, so none of the file is read."""
    monkeypatch.setattr(check_module, "MAX_FILE_BYTES", 10)
    path = _write(tmp_path, "a.py", b"a" * 11)
    reads = []
    real_read = os.read

    def read(descriptor, size):
        reads.append(size)

        return real_read(descriptor, size)

    monkeypatch.setattr(os, "read", read)

    with pytest.raises(FileTooLarge):
        read_python_file(str(path))

    assert reads == []


def test_a_missing_file_is_an_os_error(tmp_path) -> None:
    """A file that has gone is reported by the system."""
    with pytest.raises(FileNotFoundError):
        read_python_file(str(tmp_path / "gone.py"))


def test_the_file_is_closed_even_when_it_is_refused(
    tmp_path,
    monkeypatch,
) -> None:
    """A refused file does not leave a descriptor open."""
    closed = []
    real_close = os.close

    def close(descriptor):
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(
        check_module,
        "_status_of",
        lambda descriptor: _info(stat.S_IFIFO | 0o644),
    )
    path = _write(tmp_path, "a.py")

    with pytest.raises(NotRegularFile):
        read_python_file(str(path))

    assert len(closed) == 1


def test_a_real_pipe_is_skipped_and_does_not_block(tmp_path) -> None:
    """A pipe named like a Python file is not read, and nothing hangs.

    Only a system that has named pipes can make one, so this checks
    nothing on Windows. The run is in a thread, so that a mistake fails
    this test and does not hang the suite.
    """
    if not hasattr(os, "mkfifo"):
        return

    pipe = tmp_path / "pipe.py"
    os.mkfifo(pipe)
    outcome = []

    def work():
        try:
            read_python_file(str(pipe))
            outcome.append("read")
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(5)

    assert len(outcome) == 1
    assert isinstance(outcome[0], NotRegularFile)


def test_a_real_link_to_a_file_is_not_followed(tmp_path) -> None:
    """A link named like a Python file is refused when it is opened.

    Where links cannot be made, or the system cannot refuse them at the
    open, this checks nothing. The walk skips links before the open.
    """
    if not hasattr(os, "O_NOFOLLOW"):
        return

    target = _write(tmp_path, "target.py")

    try:
        os.symlink(target, tmp_path / "link.py")
    except (OSError, NotImplementedError):
        return

    with pytest.raises(OSError):
        read_python_file(str(tmp_path / "link.py"))


def test_an_empty_directory_has_nothing_to_report(tmp_path) -> None:
    """All counts are zero, and there are no problems."""
    assert check_directory(tmp_path) == Report()


def test_a_directory_that_is_missing_is_an_os_error(tmp_path) -> None:
    """The directory itself must be readable."""
    with pytest.raises(FileNotFoundError):
        check_directory(tmp_path / "gone")


def test_valid_files_in_nested_directories_are_counted(tmp_path) -> None:
    """The count and the total are those of the files that were read."""
    _write(tmp_path, "a.py", "x = 1\n")
    _write(tmp_path, "pkg/b.py", "y = 22\n")
    _write(tmp_path, "pkg/deep/c.py", "z = 333\n")

    report = check_directory(tmp_path)

    assert report.checked == 3
    assert report.total_bytes == len("x = 1\n" + "y = 22\n" + "z = 333\n")
    assert report.problems == []
    assert (report.too_large, report.not_read) == (0, 0)
    assert report.skipped_directories == 0


def test_problems_are_named_from_the_project_in_name_order(tmp_path) -> None:
    """A name has / between its parts, and the order is that of the names."""
    _write(tmp_path, "z.py", "return 1\n")
    _write(tmp_path, "a/c.py", "print 'x'\n")
    _write(tmp_path, "a/b.py", "x = (\n")
    _write(tmp_path, "m.py", "nonlocal q\n")
    _write(tmp_path, "ok.py")

    report = check_directory(tmp_path)

    assert report.checked == 5
    assert [p.name for p in report.problems] == [
        "a/b.py",
        "a/c.py",
        "m.py",
        "z.py",
    ]
    assert all(isinstance(p, SyntaxProblem) for p in report.problems)


def test_only_files_that_end_in_py_are_read(tmp_path) -> None:
    """Stubs, scripts, other suffixes and other cases are left alone."""
    for name in (
        "a.pyi",
        "b.pyw",
        "c.txt",
        "d.PY",
        "e",
        "f.py.txt",
        "g.pyc",
    ):
        _write(tmp_path, name, "this is ( not python\n")

    assert check_directory(tmp_path) == Report()


def test_directories_on_the_list_are_skipped_and_counted(tmp_path) -> None:
    """Nothing inside them is read, and each is counted once."""
    _write(tmp_path, "ok.py")

    for name in sorted(check_module.SKIPPED_NAMES):
        _write(tmp_path, name + "/inner/bad.py", "def f(:\n")

    report = check_directory(tmp_path)

    assert report.checked == 1
    assert report.problems == []
    assert report.skipped_directories == len(check_module.SKIPPED_NAMES)


def test_the_list_of_names_does_not_depend_on_case(tmp_path) -> None:
    """On Windows .Git is the same directory as .git."""
    _write(tmp_path, ".Git/bad.py", "def f(:\n")
    _write(tmp_path, "NODE_MODULES/bad.py", "def f(:\n")

    report = check_directory(tmp_path)

    assert report.checked == 0
    assert report.skipped_directories == 2


def test_directories_with_similar_names_are_checked(tmp_path) -> None:
    """Only the listed names are skipped, and not a name that holds one."""
    for name in ("git", "node_modules_x", "my__pycache__", "venv", "env"):
        _write(tmp_path, name + "/a.py")

    report = check_directory(tmp_path)

    assert report.checked == 5
    assert report.skipped_directories == 0


def test_a_virtual_environment_is_skipped_by_its_marker(tmp_path) -> None:
    """The file pyvenv.cfg makes a directory a virtual environment."""
    _write(tmp_path, "src/ok.py")
    _write(tmp_path, "myenv/pyvenv.cfg", "home = /usr\n")
    _write(tmp_path, "myenv/lib/bad.py", "def f(:\n")
    _write(tmp_path, "pkg/inner/PYVENV.CFG", "home = /usr\n")
    _write(tmp_path, "pkg/inner/bad.py", "def f(:\n")

    report = check_directory(tmp_path)

    assert report.checked == 1
    assert report.problems == []
    assert report.skipped_directories == 2


def test_the_directory_that_is_checked_is_never_skipped(tmp_path) -> None:
    """A project that is itself a virtual environment is still checked."""
    _write(tmp_path, "pyvenv.cfg", "home = /usr\n")
    _write(tmp_path, "a.py")

    report = check_directory(tmp_path)

    assert report.checked == 1
    assert report.skipped_directories == 0


def test_a_linked_directory_is_not_followed(tmp_path) -> None:
    """A link or a junction to a directory is not looked inside."""
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    _write(project, "own.py")
    _write(outside, "elsewhere.py", "def f(:\n")

    with _linked(project / "link", outside):
        report = check_directory(project)

    assert report.checked == 1
    assert report.problems == []
    assert report.not_read == 0


def test_a_link_named_like_a_python_file_is_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """It is counted as not read, and its target is never opened."""
    monkeypatch.setattr(check_module, "read_python_file", _unexpected)
    link = _info(stat.S_IFLNK | 0o777)
    junction = _info(stat.S_IFDIR | 0o755, st_reparse_tag=0xA0000003)
    _fake_listing(
        monkeypatch,
        tmp_path,
        [
            _entry("link.py", str(tmp_path / "link.py"), link),
            _entry("junction.py", str(tmp_path / "junction.py"), junction),
        ],
    )

    report = check_directory(tmp_path)

    assert report == Report(not_read=2)


def test_an_entry_that_is_not_a_regular_file_is_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """A pipe or a socket named like a Python file is counted and skipped."""
    monkeypatch.setattr(check_module, "read_python_file", _unexpected)
    _fake_listing(
        monkeypatch,
        tmp_path,
        [
            _entry("pipe.py", "p", _info(stat.S_IFIFO | 0o644)),
            _entry("socket.py", "s", _info(stat.S_IFSOCK | 0o644)),
            _entry("pipe.txt", "t", _info(stat.S_IFIFO | 0o644)),
        ],
    )

    assert check_directory(tmp_path) == Report(not_read=2)


def test_an_entry_whose_status_cannot_be_read_is_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """It is counted, and the rest of the directory is still checked."""
    good = _write(tmp_path, "good.py")
    real_scandir = os.scandir

    def scandir(path):
        with real_scandir(path) as scan:
            entries = list(scan)

        return _Scan([_entry("denied.py", "d", None)] + entries)

    monkeypatch.setattr(os, "scandir", scandir)

    report = check_directory(tmp_path)

    assert good.exists()
    assert report.checked == 1
    assert report.not_read == 1


def test_a_file_that_cannot_be_opened_is_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason of the system is not needed, only the count."""
    _write(tmp_path, "a.py")
    _write(tmp_path, "b.py")

    def refuse(path):
        raise PermissionError("denied")

    monkeypatch.setattr(check_module, "read_python_file", refuse)

    assert check_directory(tmp_path) == Report(not_read=2)


def test_a_directory_that_cannot_be_listed_is_counted(
    tmp_path,
    monkeypatch,
) -> None:
    """Below the top an unreadable directory is counted, not fatal."""
    _write(tmp_path, "ok.py")
    _write(tmp_path, "locked/a.py")
    real_scandir = os.scandir

    def scandir(path):
        if os.fspath(path).endswith("locked"):
            raise PermissionError("denied")

        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)

    report = check_directory(tmp_path)

    assert report.checked == 1
    assert report.not_read == 1


def test_the_top_directory_that_cannot_be_listed_is_an_error(
    tmp_path,
    monkeypatch,
) -> None:
    """The caller is told why, so that the run fails with a reason."""

    def scandir(path):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "scandir", scandir)

    with pytest.raises(PermissionError):
        check_directory(tmp_path)


def test_a_file_over_the_limit_is_counted_and_not_read(
    tmp_path,
    monkeypatch,
) -> None:
    """A big file is a fact about one file, so the run goes on."""
    monkeypatch.setattr(check_module, "MAX_FILE_BYTES", 10)
    _write(tmp_path, "small.py", "a" * 10)
    _write(tmp_path, "big.py", "def f(:\n" + "a" * 20)

    report = check_directory(tmp_path)

    assert report.checked == 1
    assert report.too_large == 1
    assert report.problems == []
    assert report.total_bytes == 10


def test_a_file_that_grew_while_it_was_read_is_too_large(
    tmp_path,
    monkeypatch,
) -> None:
    """The walk counts what the reader says, as well as what it listed."""
    _write(tmp_path, "a.py")

    def grown(path):
        raise FileTooLarge(path)

    monkeypatch.setattr(check_module, "read_python_file", grown)

    assert check_directory(tmp_path) == Report(too_large=1)


def test_too_many_files_stop_the_check(tmp_path, monkeypatch) -> None:
    """One file over the limit stops it, and a file at the limit does not."""
    monkeypatch.setattr(check_module, "MAX_FILES", 3)
    monkeypatch.setattr(check_module, "MAX_FILE_BYTES", 10)
    _write(tmp_path, "a.py")
    _write(tmp_path, "b.py")
    _write(tmp_path, "big.py", "a" * 20)

    assert check_directory(tmp_path).too_large == 1

    _write(tmp_path, "c.py")

    with pytest.raises(LimitReached) as caught:
        check_directory(tmp_path)

    assert caught.value.reason == "too many Python files: more than 3"
    assert isinstance(caught.value, Exception)
    assert str(caught.value) == caught.value.reason


def test_files_that_are_not_python_do_not_count_to_the_limit(
    tmp_path,
    monkeypatch,
) -> None:
    """Only the files that would be checked are counted."""
    monkeypatch.setattr(check_module, "MAX_FILES", 2)
    _write(tmp_path, "a.py")
    _write(tmp_path, "b.py")

    for number in range(5):
        _write(tmp_path, f"data{number}.txt")

    assert check_directory(tmp_path).checked == 2


def test_too_much_code_stops_the_check(tmp_path, monkeypatch) -> None:
    """The total is of what was read, and the reason gives the limit."""
    monkeypatch.setattr(check_module, "MAX_TOTAL_BYTES", 20)
    _write(tmp_path, "a.py", "a" * 10)
    _write(tmp_path, "b.py", "b" * 10)

    assert check_directory(tmp_path).total_bytes == 20

    _write(tmp_path, "c.py", "c")

    with pytest.raises(LimitReached) as caught:
        check_directory(tmp_path)

    assert caught.value.reason == "too much Python code: more than 20 B"


def test_the_report_does_not_depend_on_the_order_of_the_listing(
    tmp_path,
    monkeypatch,
) -> None:
    """The system may list files in any order, and the report is the same."""
    _write(tmp_path, "a.py")
    _write(tmp_path, "b/c.py", "x = (\n")
    _write(tmp_path, "b/d.py", "return 1\n")
    _write(tmp_path, "e/f.py")
    _write(tmp_path, "g.py", "break\n")
    expected = check_directory(tmp_path)
    real_scandir = os.scandir

    def reversed_listing(path):
        with real_scandir(path) as scan:
            entries = list(scan)

        return _Scan(list(reversed(entries)))

    monkeypatch.setattr(os, "scandir", reversed_listing)

    assert check_directory(tmp_path) == expected
    assert [p.name for p in expected.problems] == ["b/c.py", "b/d.py", "g.py"]


def test_a_check_writes_nothing_and_runs_nothing(tmp_path) -> None:
    """The project is the same afterwards, with no bytecode and no marker."""
    marker = tmp_path / "marker"
    _write(
        tmp_path,
        "evil.py",
        f"open({str(marker)!r}, 'w').write('ran')\nraise SystemExit(3)\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py", "import evil\n")
    before = _listing(tmp_path)

    report = check_directory(tmp_path)

    assert report.checked == 3
    assert report.problems == []
    assert not marker.exists()
    assert _listing(tmp_path) == before


def test_the_python_that_judges_the_files_is_named() -> None:
    """The version is the major and the minor number of this Python."""
    assert python_version() == (
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )


def test_a_report_is_described_in_one_line() -> None:
    """The form is fixed, with the counts first and the errors after."""
    report = Report(
        checked=41,
        too_large=1,
        skipped_directories=3,
        problems=[
            SyntaxProblem("pkg/a.py", 3, "invalid syntax"),
            SyntaxProblem("pkg/b.py", None, "unterminated string literal"),
        ],
    )

    assert describe(report) == (
        f"checked Python syntax with Python {python_version()}: "
        "41 files checked, 2 with errors, 1 too large, 0 not read, "
        "3 directories skipped; errors: "
        "pkg/a.py line 3: invalid syntax; "
        "pkg/b.py: unterminated string literal"
    )


def test_a_report_without_problems_has_no_errors_part() -> None:
    """A clean check says how much was checked, and nothing else."""
    text = describe(Report(checked=1))

    assert text == (
        f"checked Python syntax with Python {python_version()}: "
        "1 files checked, 0 with errors, 0 too large, 0 not read, "
        "0 directories skipped"
    )
    assert "errors:" not in text


def test_only_the_first_problems_are_shown_but_all_are_counted() -> None:
    """The counts give the total, and the text gives the first ones."""
    problems = [SyntaxProblem(f"f{n}.py", n, "bad") for n in range(1, 6)]

    text = describe(Report(checked=5, problems=problems))

    assert ERRORS_SHOWN == 3
    assert "5 with errors" in text
    assert "f1.py line 1: bad; f2.py line 2: bad; f3.py line 3: bad" in text
    assert "f4.py" not in text


def test_names_and_messages_are_escaped_and_cut() -> None:
    """They are data from the project, so they cannot move the cursor."""
    problem = SyntaxProblem("a\nb.py", 2, "bad\x1b[2J" + "y" * 200)

    text = describe(Report(checked=1, problems=[problem]))

    assert "a\\x0ab.py line 2: bad\\x1b[2J" in text
    assert "\n" not in text
    assert "\x1b" not in text
    assert "y" * 100 not in text


def test_text_that_escapes_to_a_lot_is_cut_again() -> None:
    """Escapes can make text four times as long, so the output is capped."""
    shown = check_module._shown("\x1b" * 500, 60)

    assert len(shown) == 90
    assert shown.endswith("...")
    assert check_module._shown("x" * 100, 60) == "x" * 60 + "..."
    assert check_module._shown("short", 60) == "short"


def test_the_longest_description_still_fits_in_a_reason() -> None:
    """A reason is cut at 1000 characters, so this must stay under it."""
    nasty = SyntaxProblem("\x1b" * 500, 123456, "\x1b" * 500)

    text = describe(
        Report(
            checked=10000,
            too_large=10000,
            not_read=10000,
            skipped_directories=10000,
            problems=[nasty] * 5,
        )
    )

    assert len(text) < 1000
