from aic_control_centre.cli import build_parser


def test_parser_program_name():
    parser = build_parser()

    assert parser.prog == "aic"


def test_parser_description():
    parser = build_parser()

    assert parser.description == (
        "Local-first autonomous AI development and control platform."
    )


def test_version_argument():
    parser = build_parser()

    args = parser.parse_args([])

    assert args is not None


def test_task_lifecycle_commands_are_registered():
    """The task lifecycle commands are available in the CLI parser."""
    parser = build_parser()

    for command in ("ready", "start", "complete", "fail"):
        args = parser.parse_args(
            ["task", command, "task-123"],
        )

        assert args.command == "task"
        assert args.task_command == command
        assert args.task_id == "task-123"


def test_validate_command_is_registered():
    """The validate command is available in the CLI parser."""
    parser = build_parser()

    args = parser.parse_args(["validate"])

    assert args.command == "validate"


def test_task_readiness_command_is_registered():
    """The task readiness command is available in the CLI parser."""
    parser = build_parser()

    args = parser.parse_args(
        ["task", "readiness", "task-123"],
    )

    assert args.command == "task"
    assert args.task_command == "readiness"
    assert args.task_id == "task-123"
