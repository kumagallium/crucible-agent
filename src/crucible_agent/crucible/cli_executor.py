"""CLI/Library ツールのインストールと実行

Registry に登録された CLI/Library を動的にインストールし、
Agent の function calling ツールとして実行する。
"""

from __future__ import annotations

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)

# インストールコマンドの許可プレフィックス
ALLOWED_INSTALL_PREFIXES = (
    "pip install",
    "pip3 install",
    "uv pip install",
    "npm install -g",
    "npx ",
)

# タイムアウト設定（秒）
INSTALL_TIMEOUT = 120
EXECUTE_TIMEOUT = 60


def _validate_install_command(cmd: str) -> None:
    """インストールコマンドが許可パターンに一致するか検証する"""
    if not cmd.strip():
        raise ValueError("install_command が空です")
    if not any(cmd.strip().startswith(p) for p in ALLOWED_INSTALL_PREFIXES):
        raise ValueError(
            f"許可されていないインストールコマンド: {cmd!r}\n"
            f"許可パターン: {', '.join(ALLOWED_INSTALL_PREFIXES)}"
        )


class CliExecutor:
    """CLI/Library ツールのインストールと実行を管理する

    Docker コンテナ内での実行を前提とする。
    インストール済みツールはインメモリにキャッシュし、同一プロセス内で再インストールしない。
    """

    def __init__(self) -> None:
        self._installed: set[str] = set()

    async def ensure_installed(self, name: str, install_command: str) -> str:
        """ツールが未インストールならインストールする（冪等）

        Returns:
            インストール結果のメッセージ
        """
        if name in self._installed:
            return f"{name} はインストール済みです"

        _validate_install_command(install_command)

        logger.info("CLI ツールをインストール: %s (%s)", name, install_command)
        try:
            proc = await asyncio.create_subprocess_shell(
                install_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=INSTALL_TIMEOUT
            )
        except TimeoutError:
            msg = f"{name} のインストールがタイムアウトしました ({INSTALL_TIMEOUT}秒)"
            logger.error(msg)
            return msg

        if proc.returncode == 0:
            self._installed.add(name)
            logger.info("CLI ツールのインストール完了: %s", name)
            return f"{name} のインストールが完了しました"

        error_output = stderr.decode(errors="replace").strip()
        msg = f"{name} のインストールに失敗しました (exit={proc.returncode}): {error_output[:500]}"
        logger.error(msg)
        return msg

    async def execute(self, name: str, command: str, arguments: str = "") -> str:
        """CLI コマンドを実行して結果を返す

        Args:
            name: ツール名（ログ用）
            command: 実行するコマンド
            arguments: コマンド引数（shlex.quote で安全にエスケープ）
        """
        # コマンド組み立て: 引数がある場合はエスケープして結合
        if arguments:
            safe_args = shlex.quote(arguments)
            full_cmd = f"{command} {safe_args}"
        else:
            full_cmd = command

        logger.info("CLI ツールを実行: %s — %s", name, full_cmd[:200])
        try:
            proc = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=EXECUTE_TIMEOUT
            )
        except TimeoutError:
            msg = f"コマンドがタイムアウトしました ({EXECUTE_TIMEOUT}秒): {full_cmd[:200]}"
            logger.error(msg)
            return msg

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            return f"エラー (exit={proc.returncode}):\n{err[:2000]}\n{out[:2000]}"

        # stdout + stderr（警告等）を返す
        result = out
        if err:
            result += f"\n\n[stderr]\n{err[:1000]}"
        return result[:4000] if result else "(出力なし)"
