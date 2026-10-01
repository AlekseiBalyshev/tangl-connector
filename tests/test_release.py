import build_release as br


def test_allowed_next():
    assert br.allowed_next((0, 1, 0)) == {(0, 1, 1), (0, 2, 0), (1, 0, 0)}


def test_check_version():
    br.check_version("0.1.0", [])
    br.check_version("0.2.0", [(0, 1, 0)])
    try:
        br.check_version("0.3.0", [(0, 1, 0)])
    except SystemExit:
        pass
    else:
        raise AssertionError


def test_skill_zip_contents(tmp_path):
    import zipfile

    z = br.build_zip("9.9.9", tmp_path)
    names = zipfile.ZipFile(z).namelist()
    assert "tangl-connector/SKILL.md" in names
    assert "tangl-connector/tangl_connector/tools.py" in names
    assert not any(n.startswith("tangl-connector/tests") for n in names)


def test_release_notes():
    notes = br.release_notes("1.0.0")
    assert "tangl-connector-skill-v1.0.0.zip" in notes and "## Что нового" in notes
    assert "materials" in notes
