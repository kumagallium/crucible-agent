"""プロンプトプロファイルの読み込み

プロファイルは DB（profiles テーブル）で管理される。
profile パラメータには ID または名前を指定できる。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# デフォルトの基盤プロンプト（プロファイル未指定時に使用）
BASE_PROMPT = (
    "You are a helpful AI assistant powered by Crucible Agent. "
    "Use the available MCP tools to assist the user effectively. "
    "Be concise, accurate, and transparent about your capabilities and limitations."
)


async def build_instruction(
    profile: str | None = None,
    custom_instructions: str | None = None,
) -> str:
    """最終的なシステムプロンプトを構築する

    Args:
        profile: プロファイル ID または名前（None なら BASE_PROMPT のみ）
        custom_instructions: カスタム指示（末尾に追加）
    """
    instruction = BASE_PROMPT

    if profile:
        from crucible_agent.profiles.repository import get_profile, get_profile_by_name

        # ID で検索、見つからなければ名前で検索
        found = await get_profile(profile) or await get_profile_by_name(profile)
        if found:
            instruction = BASE_PROMPT + "\n\n" + found.content
            logger.info("Loaded profile '%s' (id=%s, %d chars)", found.name, found.id, len(instruction))  # noqa: E501
        else:
            logger.warning("Profile '%s' not found in DB, using base prompt", profile)

    if custom_instructions:
        instruction += f"\n\n## Additional Instructions\n{custom_instructions}"

    return instruction
