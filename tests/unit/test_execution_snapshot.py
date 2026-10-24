"""Tests for the project snapshot."""

import hashlib
import os
import stat
from types import SimpleNamespace

import pytest

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.snapshot import (
    IO_REPARSE_TAG_MOUNT_POINT,
    IO_REPARSE_TAG_SYMLINK,
    KIND_DIRECTORY,
    KIND_FILE,
    KIND_LINK,
    KIND_OTHER,
    UNREADABLE,
    Changes,
    Entry,
    classify,
    compare_snapshots,
    escape_name,
    file_digest,
    is_link,
    take_snapshot,
)


def _write(path, data=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _info(mode, **fields):
    return SimpleNamespace(
        st_mode=mode,
        st_size=fields.pop("st_size", 7),
        st_mtime_ns=fields.pop("st_mtime_ns", 11),
        **fields,
    )


def test_an_empty_directory_has_an_empty_snapshot(tmp_path) -> None:
    """Nothing below the directory means nothing in the snapshot."""
    assert take_snapshot(tmp_path) == {}


def test_files_and_directories_are_listed_by_relative_name(tmp_path) -> None:
    """Names are relative to the directory and use a slash."""
    _write(tmp_path / "a.txt")
    _write(tmp_path / "sub" / "b.txt")
    _write(tmp_path / "sub" / "deeper" / "c.txt")

    snapshot = take_snapshot(tmp_path)

    assert sorted(snapshot) == [
        "a.txt",
        "sub",
        "sub/b.txt",
        "sub/deeper",
        "sub/deeper/c.txt",
    ]
    assert snapshot["sub"].kind == KIND_DIRECTORY
    assert snapshot["sub/b.txt"].kind == KIND_FILE


def test_a_file_entry_holds_its_size_time_and_content_hash(tmp_path) -> None:
    """The three facts that the comparison uses."""
    _write(tmp_path / "a.txt", b"hello")

    entry = take_snapshot(tmp_path)["a.txt"]

    assert entry.size == 5
    assert entry.mtime_ns == (tmp_path / "a.txt").stat().st_mtime_ns
    assert entry.digest == hashlib.sha256(b"hello").hexdigest()


def test_the_same_tree_gives_equal_snapshots_and_no_changes(
    tmp_path,
) -> None:
    """Looking twice at an untouched tree finds nothing."""
    _write(tmp_path / "a.txt")
    _write(tmp_path / "sub" / "b.txt")

    first = take_snapshot(tmp_path)
    second = take_snapshot(tmp_path)

    assert first == second
    assert not compare_snapshots(first, second)


def test_a_rewrite_with_the_same_size_and_time_is_still_seen(
    tmp_path,
) -> None:
    """The content hash catches what a coarse modification time hides."""
    path = tmp_path / "f.txt"
    _write(path, b"aaaa")
    original = path.stat()
    before = take_snapshot(tmp_path)

    path.write_bytes(b"bbbb")
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    after = take_snapshot(tmp_path)

    assert after["f.txt"].size == before["f.txt"].size
    assert after["f.txt"].mtime_ns == before["f.txt"].mtime_ns
    assert compare_snapshots(before, after).changed == ("f.txt",)


def test_a_change_of_time_alone_is_seen(tmp_path) -> None:
    """Touching a file is a change, even when its content is the same."""
    path = tmp_path / "f.txt"
    _write(path)
    original = path.stat()
    before = take_snapshot(tmp_path)

    os.utime(
        path,
        ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000_000),
    )

    changes = compare_snapshots(before, take_snapshot(tmp_path))

    assert changes.changed == ("f.txt",)


def test_added_removed_and_changed_names_are_split_and_sorted(
    tmp_path,
) -> None:
    """Each name is in one list, and each list is in order."""
    _write(tmp_path / "keep.txt")
    _write(tmp_path / "edit-b.txt", b"1")
    _write(tmp_path / "edit-a.txt", b"1")
    _write(tmp_path / "gone-b.txt")
    _write(tmp_path / "gone-a.txt")
    before = take_snapshot(tmp_path)

    (tmp_path / "gone-b.txt").unlink()
    (tmp_path / "gone-a.txt").unlink()
    _write(tmp_path / "edit-b.txt", b"22")
    _write(tmp_path / "edit-a.txt", b"22")
    _write(tmp_path / "new-b.txt")
    _write(tmp_path / "new-a.txt")

    changes = compare_snapshots(before, take_snapshot(tmp_path))

    assert changes == Changes(
        added=("new-a.txt", "new-b.txt"),
        removed=("gone-a.txt", "gone-b.txt"),
        changed=("edit-a.txt", "edit-b.txt"),
    )
    assert changes


def test_every_list_of_names_is_in_order_however_many_there_are(
    tmp_path,
) -> None:
    """Thirty names in each list leave no room for a lucky order."""
    numbers = list(range(30))
    scrambled = numbers[17:] + numbers[:17]

    for number in numbers:
        _write(tmp_path / ("gone-%02d" % number))
        _write(tmp_path / ("edit-%02d" % number), b"1")

    before = take_snapshot(tmp_path)

    for number in scrambled:
        (tmp_path / ("gone-%02d" % number)).unlink()
        _write(tmp_path / ("edit-%02d" % number), b"22")
        _write(tmp_path / ("new-%02d" % number))

    changes = compare_snapshots(before, take_snapshot(tmp_path))

    assert changes.added == tuple("new-%02d" % n for n in numbers)
    assert changes.removed == tuple("gone-%02d" % n for n in numbers)
    assert changes.changed == tuple("edit-%02d" % n for n in numbers)


def test_an_empty_directory_added_or_removed_is_seen(tmp_path) -> None:
    """A directory is part of the project even when it holds nothing."""
    (tmp_path / "old").mkdir()
    before = take_snapshot(tmp_path)

    (tmp_path / "old").rmdir()
    (tmp_path / "new").mkdir()

    changes = compare_snapshots(before, take_snapshot(tmp_path))

    assert changes.added == ("new",)
    assert changes.removed == ("old",)


def test_a_file_replaced_by_a_directory_is_a_change(tmp_path) -> None:
    """A change of kind is a change."""
    _write(tmp_path / "thing")
    before = take_snapshot(tmp_path)

    (tmp_path / "thing").unlink()
    (tmp_path / "thing").mkdir()

    changes = compare_snapshots(before, take_snapshot(tmp_path))

    assert changes.changed == ("thing",)


def test_a_special_file_is_listed_and_never_opened() -> None:
    """A pipe is not read, because reading it could block."""
    info = _info(stat.S_IFIFO | 0o600)

    entry = classify("/does/not/exist", info)

    assert entry == Entry(KIND_OTHER, size=7, mtime_ns=11)


def test_a_link_is_recognised_by_its_mode_and_by_its_windows_tag() -> None:
    """Symbolic links, junctions and other links are all links."""
    plain_directory = _info(stat.S_IFDIR | 0o755)
    cloud_placeholder = _info(stat.S_IFREG | 0o644, st_reparse_tag=0x80000009)

    assert is_link(_info(stat.S_IFLNK | 0o777)) is True
    assert is_link(
        _info(
            stat.S_IFDIR | 0o755,
            st_reparse_tag=IO_REPARSE_TAG_MOUNT_POINT,
        ),
    ) is True
    assert is_link(
        _info(stat.S_IFDIR | 0o755, st_reparse_tag=IO_REPARSE_TAG_SYMLINK),
    ) is True
    assert is_link(plain_directory) is False
    assert is_link(cloud_placeholder) is False


def test_a_link_entry_holds_its_target_and_nothing_is_opened(
    monkeypatch,
) -> None:
    """A link is recorded as a link, whatever it points to."""
    monkeypatch.setattr(snapshot_module.os, "readlink", lambda path: "away")

    entry = classify("/does/not/exist", _info(stat.S_IFLNK | 0o777))

    assert entry == Entry(KIND_LINK, target="away")


def test_a_link_whose_target_cannot_be_read_is_recorded(monkeypatch) -> None:
    """An error from the file system is recorded, not raised."""

    def refuse(path):
        raise OSError("no")

    monkeypatch.setattr(snapshot_module.os, "readlink", refuse)

    entry = classify("/does/not/exist", _info(stat.S_IFLNK | 0o777))

    assert entry == Entry(KIND_LINK, target=UNREADABLE)


@pytest.mark.skipif(os.name == "nt", reason="links need a privilege here")
def test_a_real_symlink_is_not_followed(tmp_path) -> None:
    """A link out of the project, and a link back into it, add nothing."""
    outside = tmp_path / "outside"
    project = tmp_path / "project"
    _write(outside / "secret.txt", b"outside")
    _write(project / "a.txt")
    os.symlink(outside, project / "out")
    os.symlink(project / "a.txt", project / "file-link")
    os.symlink(project, project / "loop")

    before = take_snapshot(project)

    assert sorted(before) == ["a.txt", "file-link", "loop", "out"]
    assert before["out"] == Entry(KIND_LINK, target=str(outside))
    assert before["loop"].kind == KIND_LINK

    _write(outside / "secret.txt", b"changed outside")

    assert take_snapshot(project) == before

    (project / "out").unlink()
    os.symlink(tmp_path, project / "out")

    assert compare_snapshots(before, take_snapshot(project)).changed == (
        "out",
    )


def test_a_file_that_cannot_be_read_is_recorded_as_unreadable(
    tmp_path,
) -> None:
    """The same error before and after is not a change."""
    assert file_digest(str(tmp_path / "missing")) == UNREADABLE
    assert file_digest(str(tmp_path)) == UNREADABLE


def test_a_directory_that_cannot_be_read_is_recorded(
    tmp_path,
    monkeypatch,
) -> None:
    """The directory is listed as unreadable, and the walk goes on."""
    _write(tmp_path / "ok.txt")
    (tmp_path / "locked").mkdir()
    real = os.scandir

    def scandir(path):
        if os.fspath(path) == str(tmp_path / "locked"):
            raise PermissionError("denied")

        return real(path)

    monkeypatch.setattr(snapshot_module.os, "scandir", scandir)

    first = take_snapshot(tmp_path)
    second = take_snapshot(tmp_path)

    assert first["locked"] == Entry(KIND_DIRECTORY, digest=UNREADABLE)
    assert first["ok.txt"].kind == KIND_FILE
    assert first == second


def test_the_directory_itself_must_be_readable(tmp_path) -> None:
    """A missing directory, or a file, is an error that says so."""
    _write(tmp_path / "file.txt")

    with pytest.raises(OSError):
        take_snapshot(tmp_path / "missing")

    with pytest.raises(OSError):
        take_snapshot(tmp_path / "file.txt")


def test_control_characters_in_a_name_are_escaped() -> None:
    """A name cannot move the cursor or hide text."""
    assert escape_name("a\nb\tc\x00d\x1b[2J") == "a\\x0ab\\x09c\\x00d\\x1b[2J"


def test_other_characters_that_cannot_be_shown_are_escaped() -> None:
    """Separators, and bytes that were not text, are written out."""
    assert escape_name("a\u2028b") == "a\\u2028b"
    assert escape_name("a\udc80b") == "a\\udc80b"
    assert escape_name("a\U0001f600b") == "a\U0001f600b"
    assert escape_name("a\U000e0001b") == "a\\U000e0001b"


def test_a_backslash_is_doubled_and_ordinary_text_is_kept() -> None:
    """The escapes cannot be mistaken for text."""
    assert escape_name("back\\slash") == "back\\\\slash"
    assert escape_name("caf\u00e9 projet") == "caf\u00e9 projet"


def test_a_long_name_is_shortened() -> None:
    """The limit counts the name, and the dots mark the cut."""
    assert escape_name("x" * 100, limit=10) == "x" * 10 + "..."
    assert escape_name("x" * 10, limit=10) == "x" * 10
