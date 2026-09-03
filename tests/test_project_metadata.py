from craft import PROJECT_FULL_NAME, PROJECT_NAME, __version__


def test_project_metadata() -> None:
    assert PROJECT_NAME == "CRAFT"
    assert "Consequence-aware Risk-Adaptive Framework" in PROJECT_FULL_NAME
    assert __version__

