import pytest

from crucible_agent.prompts.loader import (
    BASE_PROMPT,
    TEMPLATES_DIR,
    build_instruction,
    list_profiles,
    load_profile,
)


class TestListProfiles:
    def test_returns_directory_names(self, tmp_path, monkeypatch):
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = list_profiles()
        assert result == ["alpha", "beta"]

    def test_excludes_dot_dirs(self, tmp_path, monkeypatch):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = list_profiles()
        assert result == ["visible"]

    def test_returns_empty_when_no_templates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path / "nonexistent")
        result = list_profiles()
        assert result == []

    def test_excludes_files(self, tmp_path, monkeypatch):
        (tmp_path / "profile_dir").mkdir()
        (tmp_path / "readme.md").write_text("not a dir")
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = list_profiles()
        assert result == ["profile_dir"]


class TestLoadProfile:
    def test_existing_profile(self, tmp_path, monkeypatch):
        profile_dir = tmp_path / "science"
        profile_dir.mkdir()
        (profile_dir / "01_intro.md").write_text("Science intro")
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = load_profile("science")
        assert result.startswith(BASE_PROMPT)
        assert "Science intro" in result

    def test_nonexistent_profile_returns_base(self, tmp_path, monkeypatch):
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = load_profile("nonexistent")
        assert result == BASE_PROMPT


class TestBuildInstruction:
    def test_no_args_returns_base(self):
        result = build_instruction()
        assert result == BASE_PROMPT

    def test_with_profile(self, tmp_path, monkeypatch):
        profile_dir = tmp_path / "general"
        profile_dir.mkdir()
        (profile_dir / "system.md").write_text("General prompt")
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = build_instruction(profile="general")
        assert "General prompt" in result

    def test_with_custom_instructions(self):
        result = build_instruction(custom_instructions="Always respond in Japanese")
        assert result.startswith(BASE_PROMPT)
        assert "## Additional Instructions" in result
        assert "Always respond in Japanese" in result

    def test_with_profile_and_custom(self, tmp_path, monkeypatch):
        profile_dir = tmp_path / "test"
        profile_dir.mkdir()
        (profile_dir / "base.md").write_text("Test profile")
        monkeypatch.setattr("crucible_agent.prompts.loader.TEMPLATES_DIR", tmp_path)
        result = build_instruction(profile="test", custom_instructions="Be brief")
        assert "Test profile" in result
        assert "Be brief" in result
