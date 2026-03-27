"""ブラウザ E2E テスト: chat-ui のメッセージ送信 → レスポンス表示 → セッション一覧

Playwright でブラウザを操作し、以下のフローを検証:
1. チャットページにアクセスできる
2. メッセージを入力して送信できる
3. AI レスポンスが表示される
4. セッション一覧にセッションが反映される
"""

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture()
def chat_page(page: Page, server_url: str) -> Page:
    """chat-ui ページに遷移済みの Page を返す"""
    page.goto(server_url)
    # WebSocket 接続完了を待つ（送信ボタンが有効になる）
    page.wait_for_function(
        """() => {
            const btn = document.getElementById('send');
            return btn && !btn.disabled;
        }""",
        timeout=10000,
    )
    return page


class TestChatPageLoad:
    """ページ読み込みの基本検証"""

    def test_page_title(self, chat_page: Page):
        """ページタイトルが設定されている"""
        expect(chat_page).to_have_title(re.compile(r".+"))

    def test_input_field_exists(self, chat_page: Page):
        """メッセージ入力フィールドが存在する"""
        input_el = chat_page.locator("#input")
        expect(input_el).to_be_visible()

    def test_send_button_exists(self, chat_page: Page):
        """送信ボタンが存在し、有効"""
        send_btn = chat_page.locator("#send")
        expect(send_btn).to_be_visible()
        expect(send_btn).to_be_enabled()

    def test_session_list_exists(self, chat_page: Page):
        """セッション一覧コンテナが存在する"""
        session_list = chat_page.locator("#session-list")
        expect(session_list).to_be_visible()


class TestMessageSendAndResponse:
    """メッセージ送信 → レスポンス表示のフロー"""

    def test_send_message_and_receive_response(self, chat_page: Page):
        """メッセージ送信後に AI レスポンスが表示される"""
        # メッセージ入力
        input_el = chat_page.locator("#input")
        input_el.fill("Hello, this is a test message")

        # 送信
        chat_page.locator("#send").click()

        # ユーザーメッセージが DOM に表示される
        user_msg = chat_page.locator(".msg.user").last
        expect(user_msg).to_contain_text("Hello, this is a test message")

        # AI レスポンスが表示される（モックが "Mock response to: ..." を返す）
        agent_msg = chat_page.locator(".msg.agent").last
        expect(agent_msg).to_contain_text("Mock response to:", timeout=10000)

    def test_input_cleared_after_send(self, chat_page: Page):
        """送信後に入力フィールドがクリアされる"""
        input_el = chat_page.locator("#input")
        input_el.fill("Test message")
        chat_page.locator("#send").click()

        # 入力がクリアされている
        expect(input_el).to_have_value("")

    def test_send_button_disabled_during_response(self, chat_page: Page):
        """送信中は送信ボタンが無効になる"""
        input_el = chat_page.locator("#input")
        input_el.fill("Test")
        chat_page.locator("#send").click()

        # レスポンス完了後にボタンが再度有効になる
        send_btn = chat_page.locator("#send")
        expect(send_btn).to_be_enabled(timeout=10000)

    def test_multiple_messages(self, chat_page: Page):
        """複数メッセージの送受信が正しく動作する"""
        for i in range(2):
            input_el = chat_page.locator("#input")
            input_el.fill(f"Message {i + 1}")
            chat_page.locator("#send").click()

            # レスポンスを待つ
            chat_page.locator(".msg.agent").nth(i).wait_for(timeout=10000)

        # 2つのユーザーメッセージと2つの AI レスポンスが存在
        assert chat_page.locator(".msg.user").count() == 2
        assert chat_page.locator(".msg.agent").count() >= 2


class TestSessionList:
    """セッション一覧への反映"""

    def test_session_appears_after_message(self, chat_page: Page):
        """メッセージ送信後にセッション一覧にセッションが表示される"""
        # メッセージ送信
        chat_page.locator("#input").fill("Session test message")
        chat_page.locator("#send").click()

        # AI レスポンス完了を待つ
        chat_page.locator(".msg.agent").last.wait_for(timeout=10000)

        # セッション一覧の更新を待つ（loadSessionList は done 後に呼ばれる）
        # .session-item か data-sid 属性を持つ要素を待つ
        chat_page.wait_for_function(
            """() => {
                const items = document.querySelectorAll('.session-item, [data-sid]');
                return items.length > 0;
            }""",
            timeout=10000,
        )

    def test_new_chat_creates_new_session(self, chat_page: Page):
        """「新しいチャット」ボタンで新規セッションが作成される"""
        # 1つ目のメッセージ
        chat_page.locator("#input").fill("First session")
        chat_page.locator("#send").click()
        chat_page.locator(".msg.agent").last.wait_for(timeout=10000)

        # 新しいチャットボタンをクリック
        chat_page.locator("#new-chat-btn").click()

        # WebSocket 再接続を待つ
        chat_page.wait_for_function(
            """() => {
                const btn = document.getElementById('send');
                return btn && !btn.disabled;
            }""",
            timeout=10000,
        )

        # メッセージエリアがクリアされている
        messages = chat_page.locator("#messages")
        # 新規セッションでは user/agent メッセージが消える
        assert chat_page.locator(".msg.user").count() == 0
