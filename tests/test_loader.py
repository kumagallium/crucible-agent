import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from crucible_agent.prompts.loader import BASE_PROMPT, build_instruction


class TestBuildInstruction:
    @pytest.mark.asyncio
    async def test_no_args_returns_base(self):
        result = await build_instruction()
        assert result == BASE_PROMPT

    @pytest.mark.asyncio
    async def test_with_custom_instructions_only(self):
        result = await build_instruction(custom_instructions="Always respond in Japanese")
        assert result.startswith(BASE_PROMPT)
        assert "## Additional Instructions" in result
        assert "Always respond in Japanese" in result

    @pytest.mark.asyncio
    async def test_with_profile_found_by_id(self):
        mock_profile = MagicMock(id="test-id", name="general", content="## General\nHello from DB")
        with (
            patch("crucible_agent.profiles.repository.get_profile", new_callable=AsyncMock, return_value=mock_profile),
            patch("crucible_agent.profiles.repository.get_profile_by_name", new_callable=AsyncMock),
        ):
            result = await build_instruction(profile="test-id")
        assert BASE_PROMPT in result
        assert "Hello from DB" in result

    @pytest.mark.asyncio
    async def test_with_profile_found_by_name(self):
        mock_profile = MagicMock(id="test-id", name="general", content="## General\nFound by name")
        with (
            patch("crucible_agent.profiles.repository.get_profile", new_callable=AsyncMock, return_value=None),
            patch("crucible_agent.profiles.repository.get_profile_by_name", new_callable=AsyncMock, return_value=mock_profile),
        ):
            result = await build_instruction(profile="general")
        assert "Found by name" in result

    @pytest.mark.asyncio
    async def test_with_profile_not_found_returns_base(self):
        with (
            patch("crucible_agent.profiles.repository.get_profile", new_callable=AsyncMock, return_value=None),
            patch("crucible_agent.profiles.repository.get_profile_by_name", new_callable=AsyncMock, return_value=None),
        ):
            result = await build_instruction(profile="nonexistent")
        assert result == BASE_PROMPT

    @pytest.mark.asyncio
    async def test_with_profile_and_custom_instructions(self):
        mock_profile = MagicMock(id="test-id", name="test", content="Profile content")
        with (
            patch("crucible_agent.profiles.repository.get_profile", new_callable=AsyncMock, return_value=mock_profile),
            patch("crucible_agent.profiles.repository.get_profile_by_name", new_callable=AsyncMock),
        ):
            result = await build_instruction(profile="test-id", custom_instructions="Be brief")
        assert "Profile content" in result
        assert "Be brief" in result
