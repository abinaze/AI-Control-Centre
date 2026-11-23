"""Tests for the job object of the child of a process adapter."""

import ctypes
import os

import pytest

from aic_control_centre.execution import job as job_module
from aic_control_centre.execution.job import (
    EXTENDED_LIMIT_INFORMATION,
    LIMIT_KILL_ON_JOB_CLOSE,
    LIMIT_PROCESS_MEMORY,
    MEBIBYTE,
    ExtendedLimits,
    Job,
    create_job,
    limit_information,
)


class FakeKernel:
    """Records the calls of the job, and answers with what it is told."""

    def __init__(self, assigns=True):
        self.assigns = assigns
        self.calls = []

    def AssignProcessToJobObject(self, job, process):
        self.calls.append(("assign", job, process))

        return 1 if self.assigns else 0

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))

        return 1


class FakeProcess:
    def __init__(self, handle):
        self._handle = handle


def test_the_constants_are_the_ones_of_windows() -> None:
    """The flags and the class of information are fixed by the system."""
    assert LIMIT_PROCESS_MEMORY == 0x100
    assert LIMIT_KILL_ON_JOB_CLOSE == 0x2000
    assert EXTENDED_LIMIT_INFORMATION == 9
    assert MEBIBYTE == 1024 * 1024


def test_the_structure_of_the_limits_has_the_size_that_windows_expects(
) -> None:
    """144 bytes on a 64-bit build. It checks nothing on a 32-bit one."""
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return

    assert ctypes.sizeof(ExtendedLimits) == 144


def test_a_job_always_kills_on_close() -> None:
    """With no memory limit, only the kill-on-close flag is set."""
    information = limit_information(None)

    assert information.BasicLimitInformation.LimitFlags == 0x2000
    assert information.ProcessMemoryLimit == 0


def test_a_memory_limit_is_set_in_bytes_with_its_flag() -> None:
    """MiB become bytes, and the flag for the limit is added."""
    information = limit_information(512)

    assert information.BasicLimitInformation.LimitFlags == 0x2100
    assert information.ProcessMemoryLimit == 512 * 1024 * 1024

    half = limit_information(0.5)

    assert half.ProcessMemoryLimit == 512 * 1024


def test_no_other_limit_is_set() -> None:
    """No limit on CPU time, on the job as a whole, or on the processes."""
    information = limit_information(100)
    basic = information.BasicLimitInformation

    assert basic.PerProcessUserTimeLimit == 0
    assert basic.PerJobUserTimeLimit == 0
    assert basic.ActiveProcessLimit == 0
    assert information.JobMemoryLimit == 0


@pytest.mark.parametrize("memory", [0, -1, -0.5])
def test_a_memory_limit_must_be_greater_than_zero(memory) -> None:
    """It is refused before anything is made, on every system."""
    with pytest.raises(ValueError):
        limit_information(memory)

    with pytest.raises(ValueError):
        create_job(memory)


def test_there_is_no_job_off_windows() -> None:
    """It checks nothing on Windows, where a real job is made."""
    if os.name == "nt":
        return

    assert create_job() is None
    assert create_job(512) is None


def test_assign_gives_the_handle_of_the_child_to_the_system() -> None:
    """The job handle and the process handle, in that order."""
    kernel = FakeKernel()
    job = Job(41, kernel)

    job.assign(FakeProcess(77))

    assert kernel.calls == [("assign", 41, 77)]


def test_a_failed_assignment_is_an_error() -> None:
    """The caller decides what to do about it."""
    job = Job(41, FakeKernel(assigns=False))

    with pytest.raises(OSError) as raised:
        job.assign(FakeProcess(77))

    assert "AssignProcessToJobObject failed" in str(raised.value)


def test_a_child_without_a_handle_is_an_error() -> None:
    """A process object from another system has none."""
    kernel = FakeKernel()
    job = Job(41, kernel)

    with pytest.raises(OSError):
        job.assign(object())

    assert kernel.calls == []


def test_close_closes_the_handle_once() -> None:
    """A second close does nothing, and a closed job takes no child."""
    kernel = FakeKernel()
    job = Job(41, kernel)

    job.close()
    job.close()

    assert kernel.calls == [("close", 41)]

    with pytest.raises(OSError):
        job.assign(FakeProcess(77))

    assert kernel.calls == [("close", 41)]


def test_close_does_not_raise_when_the_system_says_no() -> None:
    """Closing is the last thing that is done, so it must not fail."""
    class Refusing(FakeKernel):
        def CloseHandle(self, handle):
            self.calls.append(("close", handle))

            return 0

    kernel = Refusing()
    Job(41, kernel).close()

    assert kernel.calls == [("close", 41)]


def test_the_module_makes_no_call_to_the_system_when_it_is_imported() -> None:
    """The functions are loaded when they are first needed."""
    assert job_module._KERNEL == [] or os.name == "nt"
