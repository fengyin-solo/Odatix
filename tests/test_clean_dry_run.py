"""
"odatix clean --dry-run": list, one by one, what a clean would remove or
refuse, delete nothing, and leave every file and directory in place.

Covers files, directories, the dangerous-path refusal, a profile that matches
nothing, and the workspace tree being identical before and after the preview.
"""

import os

import odatix.components.clean as clean
from odatix.workspace.clean import CleanSettingsFile, remove_path as workspace_remove_path


def _profile(tmp_path, patterns):
    """A clean settings file listing `patterns` (YAML-quoted) in `tmp_path`."""
    path = tmp_path / "clean_settings.yml"
    content = "remove_list:\n" + "".join('  - "{0}"\n'.format(pattern) for pattern in patterns)
    path.write_text(content, encoding="utf-8")
    return path


def _snapshot(root):
    """Every directory and file under `root`, files with their exact content."""
    dirs = []
    files = {}
    for base, dirnames, filenames in os.walk(str(root)):
        for name in dirnames:
            dirs.append(os.path.relpath(os.path.join(base, name), str(root)))
        for name in filenames:
            full = os.path.join(base, name)
            with open(full, "rb") as handle:
                files[os.path.relpath(full, str(root))] = handle.read()
    return sorted(dirs), files


######################################
# Command line component
######################################

def test_dry_run_previews_a_file_without_deleting_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    target = tmp_path / "vivado.log"
    target.write_text("litter\n", encoding="utf-8")
    profile = _profile(tmp_path, ["vivado.log"])

    assert clean.clean(str(profile), dry_run=True) is True
    out = capsys.readouterr().out

    assert "Dry run: nothing will be deleted" in out
    assert 'Would remove "vivado.log" (file)' in out
    assert "Removed " not in out
    assert target.read_text(encoding="utf-8") == "litter\n"


def test_dry_run_previews_a_directory_without_deleting_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    build = tmp_path / "build"
    build.mkdir()
    (build / "a.tmp").write_text("a", encoding="utf-8")
    nested = build / "nested"
    nested.mkdir()
    (nested / "b.tmp").write_text("b", encoding="utf-8")
    profile = _profile(tmp_path, ["build"])

    clean.clean(str(profile), dry_run=True)
    out = capsys.readouterr().out

    assert 'Would remove "build" (directory)' in out
    assert build.is_dir()
    assert (build / "a.tmp").is_file()
    assert (nested / "b.tmp").is_file()


def test_dry_run_lists_every_match_of_a_glob(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    (tmp_path / "one.log").write_text("1", encoding="utf-8")
    (tmp_path / "two.log").write_text("2", encoding="utf-8")
    profile = _profile(tmp_path, ["*.log"])

    clean.clean(str(profile), dry_run=True)
    out = capsys.readouterr().out

    assert 'Would remove "one.log" (file)' in out
    assert 'Would remove "two.log" (file)' in out
    assert (tmp_path / "one.log").is_file()
    assert (tmp_path / "two.log").is_file()


def test_dry_run_reports_a_dangerous_pattern_as_left_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    keep = tmp_path / "keep.txt"
    keep.write_text("keep\n", encoding="utf-8")
    profile = _profile(tmp_path, ["*"])

    clean.clean(str(profile), dry_run=True)
    out = capsys.readouterr().out

    assert "seems dangerous" in out
    assert "would be left alone" in out
    assert "Would remove" not in out
    assert keep.exists()
    assert tmp_path.is_dir()


def test_dry_run_with_yes_previews_each_match_but_keeps_them(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    keep = tmp_path / "keep.txt"
    keep.write_text("keep\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inside.txt").write_text("in\n", encoding="utf-8")
    profile = _profile(tmp_path, ["*"])

    clean.clean(str(profile), force=True, dry_run=True)
    out = capsys.readouterr().out

    # Forced, the dangerous "*" is resolved like any glob and every match is
    # previewed -- still without deleting anything.
    assert "seems dangerous" not in out
    assert 'Would remove "keep.txt" (file)' in out
    assert 'Would remove "sub" (directory)' in out
    assert keep.is_file()
    assert (sub / "inside.txt").is_file()
    assert tmp_path.is_dir()


def test_dry_run_says_when_no_pattern_matches(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    profile = _profile(tmp_path, ["nothing_here"])

    clean.clean(str(profile), dry_run=True)
    out = capsys.readouterr().out

    assert "Nothing to clean" in out
    assert "none of the 1 patterns" in out
    assert "Would remove" not in out


def test_dry_run_leaves_the_whole_tree_unchanged(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    build = tmp_path / "build"
    build.mkdir()
    (build / "one.tmp").write_text("1", encoding="utf-8")
    log = tmp_path / "vivado.log"
    log.write_text("log\n", encoding="utf-8")
    keep = tmp_path / "important.v"
    keep.write_text("module important;\n", encoding="utf-8")
    profile = _profile(tmp_path, ["vivado.log", "build", "missing"])

    before = _snapshot(tmp_path)
    assert clean.clean(str(profile), dry_run=True) is True
    assert _snapshot(tmp_path) == before
    capsys.readouterr()  # The comparison is what matters here, not the output.

    # The preview really did resolve the same patterns: a real clean on the
    # same profile then removes exactly what it announced.
    assert clean.clean(str(profile), quiet=True) is True
    assert not log.exists()
    assert not build.exists()
    assert keep.is_file()


######################################
# Workspace API (odatix.workspace.clean)
######################################

def test_workspace_remove_path_dry_run_previews_file_and_directory(tmp_path):
    a_file = tmp_path / "a.log"
    a_file.write_text("x", encoding="utf-8")
    a_dir = tmp_path / "out"
    a_dir.mkdir()
    (a_dir / "nested.txt").write_text("y", encoding="utf-8")

    result = workspace_remove_path("a.log", root=str(tmp_path), dry_run=True)
    assert len(result.removed) == 1
    assert result.removed[0].path == os.path.realpath(str(a_file))
    assert result.removed[0].kind == "file"
    assert a_file.is_file()

    result = workspace_remove_path("out", root=str(tmp_path), dry_run=True)
    assert len(result.removed) == 1
    assert result.removed[0].kind == "directory"
    assert a_dir.is_dir()
    assert (a_dir / "nested.txt").is_file()


def test_workspace_remove_path_dry_run_keeps_the_dangerous_check(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inside.txt").write_text("in", encoding="utf-8")

    refused = workspace_remove_path("*", root=str(tmp_path), dry_run=True)
    assert not refused.removed
    assert len(refused.skipped) == 1
    assert marker.is_file()

    forced = workspace_remove_path("*", root=str(tmp_path), force=True, dry_run=True)
    assert {removal.kind for removal in forced.removed} == {"file", "directory"}
    assert marker.is_file()
    assert (sub / "inside.txt").is_file()
    assert tmp_path.is_dir()


def test_workspace_clean_settings_file_run_dry_run_deletes_nothing(tmp_path):
    (tmp_path / "a.log").write_text("x", encoding="utf-8")
    profile = tmp_path / "clean.yml"
    profile.write_text('remove_list:\n  - "a.log"\n  - "missing"\n', encoding="utf-8")

    settings = CleanSettingsFile(str(profile), root=str(tmp_path))
    result = settings.run(dry_run=True)

    assert len(result.removed) == 1
    assert result.removed[0].kind == "file"
    assert len(result.unmatched) == 1
    assert (tmp_path / "a.log").is_file()
