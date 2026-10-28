"""Tests for looking at a project directory."""

import builtins
import contextlib
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

from aic_control_centre.execution import inspect_project as inspect_module
from aic_control_centre.execution.inspect_project import (
    Summary,
    describe,
    format_size,
    inspect_directory,
    record,
)


def _write(path, data=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _info(mode, size=7, **fields):
    return SimpleNamespace(st_mode=mode, st_size=size, **fields)


def _file(size=7):
    return _info(stat.S_IFREG | 0o644, size)


def _directory():
    return _info(stat.S_IFDIR | 0o755, 0)


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


def test_a_regular_file_is_counted_with_its_size() -> None:
    """A file adds to the count, the total and the largest list."""
    summary = Summary()

    descend = record(summary, "a.txt", _file(5))

    assert descend is False
    assert summary.files == 1
    assert summary.total_bytes == 5
    assert summary.largest == [(5, "a.txt")]


def test_a_directory_is_counted_and_looked_inside() -> None:
    """Only a directory is descended into."""
    summary = Summary()

    assert record(summary, "sub", _directory()) is True
    assert summary.directories == 1
    assert summary.files == 0


def test_a_link_is_counted_and_never_looked_inside() -> None:
    """A link is not followed, whether it is a symlink or a junction."""
    summary = Summary()
    symlink = _info(stat.S_IFLNK | 0o777)
    junction = _info(stat.S_IFDIR | 0o755, st_reparse_tag=0xA0000003)

    assert record(summary, "one", symlink) is False
    assert record(summary, "two", junction) is False
    assert summary.links == 2
    assert summary.directories == 0
    assert summary.files == 0


def test_a_special_file_is_counted_as_other() -> None:
    """A pipe is counted and never looked inside."""
    summary = Summary()

    assert record(summary, "pipe", _info(stat.S_IFIFO | 0o600)) is False
    assert summary.other == 1
    assert summary.files == 0
    assert summary.total_bytes == 0


def test_the_largest_files_are_by_size_and_then_by_name() -> None:
    """Three are kept, and ties are broken by name, whatever the order."""
    summary = Summary()
    names = ["f", "c", "h", "a", "g", "d", "b", "e"]

    for name in names:
        record(summary, name, _file(10))

    record(summary, "small", _file(1))
    record(summary, "big", _file(99))
    record(summary, "mid", _file(50))

    assert summary.largest == [(99, "big"), (50, "mid"), (10, "a")]
    assert summary.files == 11
    assert summary.total_bytes == 99 + 50 + 1 + 80


def test_a_readme_counts_at_the_top_level_in_any_case() -> None:
    """README, readme.md and Readme.txt are READMEs."""
    for name in ("README", "readme.md", "Readme.txt"):
        summary = Summary()

        record(summary, name, _file())

        assert summary.has_readme is True


def test_a_readme_below_the_top_does_not_count() -> None:
    """A README in a directory is not the README of the project."""
    summary = Summary()

    record(summary, "docs/README.md", _file())
    record(summary, "readme-assets/logo.png", _file())

    assert summary.has_readme is False


def test_something_else_called_readme_does_not_count() -> None:
    """A directory called readme, or a name that only contains it."""
    summary = Summary()

    record(summary, "readme-assets", _directory())
    record(summary, "notes-readme.txt", _file())

    assert summary.has_readme is False


def test_a_git_directory_or_file_counts_at_the_top_level_only() -> None:
    """A .git can be a directory, or a file in a worktree."""
    for info in (_directory(), _file()):
        summary = Summary()

        record(summary, ".git", info)

        assert summary.has_git is True

    summary = Summary()

    record(summary, "sub/.git", _directory())
    record(summary, ".gitignore", _file())
    record(summary, ".github", _directory())

    assert summary.has_git is False


def test_an_empty_directory_is_described_as_empty(tmp_path) -> None:
    """Nothing in it gives zeros and no largest file."""
    summary = inspect_directory(tmp_path)

    assert summary == Summary()
    assert describe(summary) == (
        "inspected project: 0 files, 0 directories, 0 B; largest: none; "
        "README: no; .git: no"
    )


def test_a_tree_is_counted(tmp_path) -> None:
    """Files and directories at every depth are counted."""
    _write(tmp_path / "README.md", b"x" * 10)
    _write(tmp_path / "src" / "app.py", b"y" * 2000)
    _write(tmp_path / "src" / "deep" / "more.py", b"z" * 30)
    (tmp_path / ".git").mkdir()
    (tmp_path / "empty").mkdir()

    summary = inspect_directory(tmp_path)

    assert summary.files == 3
    assert summary.directories == 4
    assert summary.total_bytes == 2040
    assert summary.largest == [
        (2000, "src/app.py"),
        (30, "src/deep/more.py"),
        (10, "README.md"),
    ]
    assert summary.has_readme is True
    assert summary.has_git is True
    assert summary.unreadable == 0


def test_a_tree_with_no_readme_and_no_git(tmp_path) -> None:
    """Both are reported as absent."""
    _write(tmp_path / "a.txt")
    _write(tmp_path / "readme-assets" / "logo.png")
    _write(tmp_path / "sub" / "README.md")

    summary = inspect_directory(tmp_path)

    assert summary.has_readme is False
    assert summary.has_git is False


def test_nothing_is_opened(tmp_path, monkeypatch) -> None:
    """The walk reads listings and status, and never a file."""
    _write(tmp_path / "a.txt")
    _write(tmp_path / "sub" / "b.txt")

    def refuse(*arguments, **options):
        raise AssertionError("a file was opened")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", refuse)
        patch.setattr(os, "open", refuse)

        summary = inspect_directory(tmp_path)

    assert summary.files == 2


def test_links_are_counted_and_not_followed(tmp_path) -> None:
    """A link out of the project, and one back into it, add nothing."""
    outside = tmp_path / "outside"
    project = tmp_path / "project"
    _write(outside / "secret.txt", b"s" * 500)
    _write(project / "a.txt", b"a" * 4)

    with _linked(project / "out", outside):
        with _linked(project / "loop", project):
            summary = inspect_directory(project)

    assert summary.links == 2
    assert summary.files == 1
    assert summary.directories == 0
    assert summary.total_bytes == 4
    assert summary.largest == [(4, "a.txt")]


def test_a_directory_that_cannot_be_listed_is_counted(
    tmp_path,
    monkeypatch,
) -> None:
    """It is unreadable, it is still a directory, and the walk goes on."""
    _write(tmp_path / "ok.txt", b"12345")
    (tmp_path / "locked").mkdir()
    real = os.scandir

    def scandir(path):
        if os.fspath(path) == str(tmp_path / "locked"):
            raise PermissionError("denied")

        return real(path)

    monkeypatch.setattr(inspect_module.os, "scandir", scandir)

    summary = inspect_directory(tmp_path)

    assert summary.unreadable == 1
    assert summary.directories == 1
    assert summary.files == 1


def test_an_entry_whose_status_cannot_be_read_is_counted(
    monkeypatch,
) -> None:
    """It is unreadable, and the entries after it are still counted."""
    entries = [
        _entry("bad", "/p/bad"),
        _entry("good", "/p/good", _file(9)),
    ]
    monkeypatch.setattr(
        inspect_module.os,
        "scandir",
        lambda path: _Scan(entries),
    )

    summary = inspect_directory("/p")

    assert summary.unreadable == 1
    assert summary.files == 1
    assert summary.total_bytes == 9


def test_the_directory_itself_must_be_readable(tmp_path) -> None:
    """A missing directory, or a file, is an error that says so."""
    _write(tmp_path / "file.txt")

    with pytest.raises(OSError):
        inspect_directory(tmp_path / "missing")

    with pytest.raises(OSError):
        inspect_directory(tmp_path / "file.txt")


def test_sizes_are_given_in_bytes_or_with_one_decimal() -> None:
    """The unit changes at 1024, and a rounded 1024.0 moves up a unit."""
    assert format_size(0) == "0 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.0 KiB"
    assert format_size(1536) == "1.5 KiB"
    assert format_size(1024 * 1024 - 1) == "1.0 MiB"
    assert format_size(1024**2) == "1.0 MiB"
    assert format_size(5 * 1024**3) == "5.0 GiB"
    assert format_size(1024**4) == "1.0 TiB"
    assert format_size(1024**5) == "1024.0 TiB"


def test_the_description_has_every_part() -> None:
    """Counts, size, links, other, unreadable, largest, README and .git."""
    summary = Summary(
        files=3,
        directories=2,
        links=1,
        other=4,
        unreadable=5,
        total_bytes=2048,
        largest=[(2000, "src/app.py"), (40, "a.txt")],
        has_readme=True,
        has_git=False,
    )

    assert describe(summary) == (
        "inspected project: 3 files, 2 directories, 2.0 KiB, "
        "1 links not followed, 4 other, 5 unreadable; "
        "largest: src/app.py (2.0 KiB), a.txt (40 B); "
        "README: yes; .git: no"
    )


def test_the_description_leaves_out_what_is_zero() -> None:
    """Links, other and unreadable appear only when there are some."""
    summary = Summary(files=1, total_bytes=7, largest=[(7, "a")])

    text = describe(summary)

    assert "links" not in text
    assert "other" not in text
    assert "unreadable" not in text
    assert text.startswith("inspected project: 1 files, 0 directories, 7 B;")


def test_names_in_the_description_are_escaped() -> None:
    """A name cannot move the cursor or hide text."""
    summary = Summary(
        files=1,
        total_bytes=3,
        largest=[(3, "a\nb\x1b[2J\\c")],
    )

    text = describe(summary)

    assert "a\\x0ab\\x1b[2J\\\\c (3 B)" in text
    assert "\n" not in text
    assert "\x1b" not in text


def test_a_long_name_is_shown_cut() -> None:
    """The name is cut and says so."""
    summary = Summary(files=1, total_bytes=1, largest=[(1, "n" * 200)])

    text = describe(summary)

    assert "n" * 60 + "... (1 B)" in text
    assert "n" * 61 not in text


def test_the_description_stays_short_whatever_the_names() -> None:
    """Names that escape to long text are cut, so the reason stays short."""
    name = "\U0010ffff" * 200
    summary = Summary(
        files=3,
        directories=1,
        links=1,
        other=1,
        unreadable=1,
        total_bytes=3 * 1024**4,
        largest=[(3, name), (2, name + "a"), (1, name + "b")],
        has_readme=True,
        has_git=True,
    )

    text = describe(summary)

    assert len(text) < 600
    assert text.endswith("README: yes; .git: yes")
    assert text.count("...") == 3
