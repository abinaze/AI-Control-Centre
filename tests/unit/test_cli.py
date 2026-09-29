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
