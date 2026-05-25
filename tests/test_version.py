from khervepdf import __version__, version_string


def test_version_string_format():
    assert __version__.count(".") == 1, "major.minor only"
    s = version_string()
    assert s.startswith(f"v{__version__}")
