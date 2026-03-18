"""プロンプトプロファイルの読み込み・切り替え

templates/ 配下のディレクトリ = プロファイル名
各プロファイルに含まれる .md ファイルがシステムプロンプトになる。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# デフォルトの基盤プロンプト（全プロファイル共通で先頭に付く）
BASE_PROMPT = (
    "You are a helpful AI assistant powered by Crucible Agent. "
    "Use the available MCP tools to assist the user effectively. "
    "Be concise, accurate, and transparent about your capabilities and limitations."
)


def list_profiles() -> list[str]:
    """利用可能なプロファイル名一覧を返す"""
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(
        d.name for d in TEMPLATES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def load_profile(name: str) -> str:
    """プロファイル名からシステムプロンプトを構築する

    Args:
        name: プロファイル名（templates/ 配下のディレクトリ名）

    Returns:
        BASE_PROMPT + プロファイル固有のプロンプトを結合した文字列
    """
    profile_dir = TEMPLATES_DIR / name
    if not profile_dir.exists() or not profile_dir.is_dir():
        logger.warning("Profile '%s' not found, using base prompt", name)
        return BASE_PROMPT

    # プロファイル内の全 .md ファイルを読み込んで結合
    parts: list[str] = [BASE_PROMPT, ""]
    for md_file in sorted(profile_dir.glob("*.md")):
        parts.append(md_file.read_text(encoding="utf-8").strip())

    prompt = "\n\n".join(parts)
    logger.info("Loaded profile '%s' (%d chars)", name, len(prompt))
    return prompt


def build_instruction(
    profile: str | None = None,
    custom_instructions: str | None = None,
) -> str:
    """最終的なシステムプロンプトを構築する

    Args:
        profile: プロファイル名（None なら BASE_PROMPT のみ）
        custom_instructions: ユーザーのカスタム指示（末尾に追加）
    """
    if profile:
        instruction = load_profile(profile)
    else:
        instruction = BASE_PROMPT

    if custom_instructions:
        instruction += f"\n\n## Additional Instructions\n{custom_instructions}"

    return instruction
