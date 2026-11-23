"""A Windows job object for the child of a process adapter.

A job object is a group of processes that Windows keeps together. A job
that has the kill-on-close flag ends every process in it when the last
handle to the job is closed, and a handle that belongs to a process that
ends is closed by the system. So a child that is in a job is stopped when
AIC is killed hard, and a process that the child left behind is stopped
when AIC closes the job after the run. The job can also limit the memory
that one process asks for.

This is the design of docs/EXECUTION_LIMITS_DESIGN.md. It is a best
effort that is only for Windows. Nothing here runs when the module is
imported, and ``create_job`` gives back None on any other system, where
the process group of the child already does this work after a run.

What it does not do: it does not limit CPU time, files, the network or the
number of processes. It is not a sandbox. A child is put in the job after
it has started, so a process that the child starts in that short time is
not in the job. No child that AIC ships starts a process.
"""

from __future__ import annotations

import ctypes
import os

LIMIT_PROCESS_MEMORY = 0x100
LIMIT_KILL_ON_JOB_CLOSE = 0x2000
EXTENDED_LIMIT_INFORMATION = 9
MEBIBYTE = 1024 * 1024

DWORD = ctypes.c_uint32


class IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def limit_information(memory_mib: float | None) -> ExtendedLimits:
    """Return the limits of a job: kill on close, and maybe memory."""
    if memory_mib is not None and memory_mib <= 0:
        raise ValueError("memory limit must be greater than zero")

    information = ExtendedLimits()
    flags = LIMIT_KILL_ON_JOB_CLOSE

    if memory_mib is not None:
        information.ProcessMemoryLimit = int(memory_mib * MEBIBYTE)
        flags |= LIMIT_PROCESS_MEMORY

    information.BasicLimitInformation.LimitFlags = flags

    return information


def _last_error() -> int:
    """Return the last error of the system, which only Windows has."""
    getter = getattr(ctypes, "get_last_error", None)

    return getter() if getter is not None else 0


def _failure(what: str) -> OSError:
    code = _last_error()

    return OSError(code, f"{what} failed with error {code}")


class Job:
    """A job object, and the handle to it that AIC holds."""

    def __init__(self, handle, kernel) -> None:
        self._handle = handle
        self._kernel = kernel

    def assign(self, process) -> None:
        """Put a started child in the job, or raise OSError."""
        if self._handle is None:
            raise OSError("the job is closed")

        # Popen keeps the handle of the process that it started on
        # Windows. It is the handle that was used when this was tried.
        process_handle = getattr(process, "_handle", None)

        if process_handle is None:
            raise OSError("the child has no process handle")

        if not self._kernel.AssignProcessToJobObject(
            self._handle, int(process_handle)
        ):
            raise _failure("AssignProcessToJobObject")

    def close(self) -> None:
        """Close the handle, which ends what is in the job. Never raises."""
        handle, self._handle = self._handle, None

        if handle is not None:
            self._kernel.CloseHandle(handle)


_KERNEL: list = []


def _kernel():
    """Load the functions that are used, once."""
    if _KERNEL:
        return _KERNEL[0]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    kernel.CreateJobObjectW.argtypes = [pointer, ctypes.c_wchar_p]
    kernel.CreateJobObjectW.restype = pointer
    kernel.SetInformationJobObject.argtypes = [
        pointer,
        ctypes.c_int,
        pointer,
        DWORD,
    ]
    kernel.SetInformationJobObject.restype = ctypes.c_int
    kernel.AssignProcessToJobObject.argtypes = [pointer, pointer]
    kernel.AssignProcessToJobObject.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [pointer]
    kernel.CloseHandle.restype = ctypes.c_int
    _KERNEL.append(kernel)

    return kernel


def create_job(memory_mib: float | None = None) -> Job | None:
    """Make a job that ends its processes when it is closed.

    The answer is None on a system that is not Windows. On Windows a
    failure raises OSError, and the caller decides what to do. The limit
    of memory is for one process and is in MiB, or None for no limit.
    """
    information = limit_information(memory_mib)

    if os.name != "nt":
        return None

    kernel = _kernel()
    handle = kernel.CreateJobObjectW(None, None)

    if not handle:
        raise _failure("CreateJobObjectW")

    job = Job(handle, kernel)

    if not kernel.SetInformationJobObject(
        handle,
        EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = _failure("SetInformationJobObject")
        job.close()

        raise error

    return job
