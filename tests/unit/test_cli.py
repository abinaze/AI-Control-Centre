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
