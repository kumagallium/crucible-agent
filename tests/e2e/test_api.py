"""E2E API テスト — FastAPI + SQLite in-memory で全エンドポイントを統合テスト"""

import pytest


class TestHealthEndpoint:
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "components" in data
        assert data["components"]["agent"] == "ok"

    async def test_health_includes_version(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert "version" in data


class TestProfilesCRUD:
    """プロファイルの CRUD 一連フロー"""

    async def test_list_profiles_initially_empty(self, client):
        resp = await client.get("/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data

    async def test_create_profile(self, client):
        resp = await client.post("/profiles", json={
            "name": "test-profile",
            "description": "E2E test profile",
            "content": "You are a test assistant.",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-profile"
        assert "id" in data
        return data["id"]

    async def test_create_and_get_profile(self, client):
        # 作成
        create_resp = await client.post("/profiles", json={
            "name": "get-test",
            "description": "test",
            "content": "content",
        })
        assert create_resp.status_code == 201
        profile_id = create_resp.json()["id"]

        # 取得
        get_resp = await client.get(f"/profiles/{profile_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "get-test"

    async def test_update_profile(self, client):
        # 作成
        create_resp = await client.post("/profiles", json={
            "name": "update-test",
            "description": "original",
            "content": "original content",
        })
        profile_id = create_resp.json()["id"]

        # 更新
        update_resp = await client.put(f"/profiles/{profile_id}", json={
            "description": "updated",
            "content": "updated content",
        })
        assert update_resp.status_code == 200
        assert update_resp.json()["description"] == "updated"

    async def test_delete_profile(self, client):
        # 作成
        create_resp = await client.post("/profiles", json={
            "name": "delete-test",
            "description": "to be deleted",
            "content": "content",
        })
        profile_id = create_resp.json()["id"]

        # 削除
        del_resp = await client.delete(f"/profiles/{profile_id}")
        assert del_resp.status_code == 204

        # 取得 → 404
        get_resp = await client.get(f"/profiles/{profile_id}")
        assert get_resp.status_code == 404

    async def test_get_nonexistent_profile(self, client):
        resp = await client.get("/profiles/nonexistent-id")
        assert resp.status_code == 404


class TestProvenanceEndpoints:
    """Provenance API の統合テスト"""

    async def test_list_sessions_empty(self, client):
        resp = await client.get("/provenance")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)  # セッションのリストを直接返す

    async def test_get_nonexistent_session(self, client):
        resp = await client.get("/provenance/nonexistent")
        # 空リストを返す（404 ではなく）
        assert resp.status_code == 200

    async def test_delete_nonexistent_session(self, client):
        resp = await client.delete("/provenance/nonexistent")
        # 204 (no content) or 404 depending on implementation
        assert resp.status_code in (204, 404)

    async def test_get_entity_nonexistent(self, client):
        resp = await client.get("/entities/nonexistent")
        assert resp.status_code == 404

    async def test_graph_empty_session(self, client):
        resp = await client.get("/provenance/nonexistent/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []


class TestToolsEndpoint:
    async def test_tools_returns_200(self, client):
        resp = await client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data


class TestModelsEndpoint:
    async def test_models_returns_200(self, client):
        resp = await client.get("/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "default" in data


class TestFullProvenanceFlow:
    """プロファイル作成 → セッション一覧 → 削除の一連フロー"""

    async def test_profile_lifecycle(self, client):
        # 1. プロファイル作成
        resp = await client.post("/profiles", json={
            "name": "lifecycle-test",
            "description": "Full lifecycle",
            "content": "You are an assistant.",
        })
        assert resp.status_code == 201
        pid = resp.json()["id"]

        # 2. 一覧で確認
        resp = await client.get("/profiles")
        profiles = resp.json()["profiles"]
        assert any(p["id"] == pid for p in profiles)

        # 3. 更新
        resp = await client.put(f"/profiles/{pid}", json={"content": "Updated content"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated content"

        # 4. 削除
        resp = await client.delete(f"/profiles/{pid}")
        assert resp.status_code == 204

        # 5. 一覧から消えている
        resp = await client.get("/profiles")
        profiles = resp.json()["profiles"]
        assert not any(p["id"] == pid for p in profiles)
