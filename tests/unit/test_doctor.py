from aic_control_centre.doctor import (
    check_command,
    check_python,
    run_checks,
)


def test_check_python_returns_supported_version():
    result = check_python()

    assert result.name == "Python version"
    assert result.passed is True
    assert result.detail.startswith("Python ")


def test_check_command_finds_python():
    result = check_command("python")

    assert result.name == "python"
    assert result.passed is True
    assert result.detail == "available"


def test_check_command_detects_missing_command():
    result = check_command("aic-command-that-does-not-exist")

    assert result.name == "aic-command-that-does-not-exist"
    assert result.passed is False
    assert result.detail == "not found"


def test_run_checks_includes_required_checks():
    results = run_checks()

    names = [result.name for result in results]

    assert "Python version" in names
    assert "git" in names
