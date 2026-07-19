import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


_TEST_DATA = Path(tempfile.mkdtemp(prefix="koko-tests-"))
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["DEEPSEEK_BASE_URL"] = "https://example.invalid"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:test-token"
os.environ["BOT_API_KEY"] = "test-bot-key"
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["ASSET_ENCRYPTION_KEY"] = (
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
)
os.environ["SUPER_ADMIN_TELEGRAM_ID"] = "999"
os.environ["DATA_DIR"] = str(_TEST_DATA)
os.environ["DB_PATH"] = str(_TEST_DATA / "db" / "test.db")
os.environ["DOCUMENTS_DIR"] = str(_TEST_DATA / "documents")
os.environ["VECTORS_DIR"] = str(_TEST_DATA / "vectors")


from fastapi import HTTPException

from app.routers import bot, chat, documents
from app.services import ai_service, rag_service, reminder_service
from app.services.ai_service import Phase1Response


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []


class _FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.deleted = []
        self.commits = 0

    async def execute(self, _query):
        if not self.results:
            raise AssertionError("Unexpected database query")
        return _ScalarResult(self.results.pop(0))

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.commits += 1


class TelegramApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_bot_routes_reject_pending_user(self):
        pending = SimpleNamespace(status="pending")
        db = _FakeDB([pending])

        with self.assertRaises(HTTPException) as raised:
            await bot._require_user(123, db)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "pending_approval")

    async def test_direct_bot_routes_allow_approved_user(self):
        approved = SimpleNamespace(status="approved")
        db = _FakeDB([approved])

        self.assertIs(await bot._require_user(123, db), approved)

    async def test_approval_action_rejects_non_admin_actor_before_query(self):
        db = _FakeDB([])
        body = bot.BotApprovalAction(actor_telegram_id=123)

        with self.assertRaises(HTTPException) as raised:
            await bot.bot_approve_user(7, body, db)

        self.assertEqual(raised.exception.status_code, 403)


class ChatHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_does_not_persist_intermediate_response(self):
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"action":"list","domain":"task","context_scope":[],"data":{},"response":"draft"}'
                    )
                )
            ]
        )

        with (
            patch.object(ai_service, "_get_recent_history", new=AsyncMock(return_value=[])),
            patch.object(
                ai_service._client.chat.completions,
                "create",
                new=AsyncMock(return_value=completion),
            ),
            patch.object(ai_service, "save_chat_turn", new=AsyncMock()) as save_turn,
        ):
            result = await ai_service.classify_intent(1, "show tasks")

        self.assertEqual(result.action, "list")
        save_turn.assert_not_awaited()

    async def test_web_chat_saves_actual_response_once_with_web_source(self):
        user = SimpleNamespace(id=1, timezone="UTC", profile_summary="")
        db = _FakeDB([[]])
        phase1 = Phase1Response(action="list", domain="task", response="draft")

        with (
            patch.object(chat, "classify_intent", new=AsyncMock(return_value=phase1)),
            patch.object(
                chat,
                "_execute_read",
                new=AsyncMock(return_value={"response": "actual task list", "data": {}}),
            ),
            patch.object(chat, "save_chat_turn", new=AsyncMock()) as save_turn,
        ):
            result = await chat.web_chat_message(
                chat.ChatMessageRequest(message="show tasks"),
                user,
                db,
            )

        self.assertEqual(result, {"response": "actual task list"})
        save_turn.assert_awaited_once_with(
            1,
            "show tasks",
            "actual task list",
            "web",
            db=db,
        )

    async def test_telegram_chat_saves_actual_response_once(self):
        user = SimpleNamespace(
            id=2,
            status="approved",
            timezone="UTC",
            profile_summary="",
        )
        db = _FakeDB([[]])
        phase1 = Phase1Response(action="list", domain="task", response="draft")

        with (
            patch.object(bot, "_get_or_create_user", new=AsyncMock(return_value=user)),
            patch.object(bot, "classify_intent", new=AsyncMock(return_value=phase1)),
            patch.object(
                bot,
                "_execute_read",
                new=AsyncMock(return_value={"response": "actual task list", "data": {}}),
            ),
            patch.object(bot, "save_chat_turn", new=AsyncMock()) as save_turn,
        ):
            result = await bot.bot_intent(
                bot.IntentRequest(telegram_id=123, message="show tasks"),
                db,
            )

        self.assertEqual(result["response"], "actual task list")
        save_turn.assert_awaited_once_with(
            2,
            "show tasks",
            "actual task list",
            "telegram",
            db=db,
        )


class DocumentDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_chunks_are_deleted_by_document_metadata(self):
        collection = Mock()

        with patch.object(rag_service, "_get_collection", return_value=collection):
            await rag_service.delete_document_index(5, 17)

        collection.delete.assert_called_once_with(where={"doc_id": 17})

    async def test_document_endpoint_removes_vectors_file_and_row(self):
        user = SimpleNamespace(id=1)
        user_dir = Path(os.environ["DOCUMENTS_DIR"]) / "1"
        user_dir.mkdir(parents=True, exist_ok=True)
        file_path = user_dir / "stored.txt"
        file_path.write_text("content")
        doc = SimpleNamespace(id=17, file_path=str(file_path))
        db = _FakeDB([doc])

        with patch.object(
            documents,
            "delete_document_index",
            new=AsyncMock(),
        ) as delete_index:
            await documents.delete_document(17, user, db)

        delete_index.assert_awaited_once_with(1, 17)
        self.assertFalse(file_path.exists())
        self.assertEqual(db.deleted, [doc])
        self.assertEqual(db.commits, 1)


class SchedulerAndDocumentationTests(unittest.TestCase):
    def test_web_app_does_not_start_scheduler(self):
        main_source = Path("backend/app/main.py").read_text()
        self.assertNotIn("start_scheduler", main_source)
        self.assertNotIn("stop_scheduler", main_source)

    def test_scheduler_jobs_check_each_minute(self):
        scheduler = Mock()

        with patch.object(reminder_service, "scheduler", scheduler):
            reminder_service.start_scheduler()

        self.assertEqual(scheduler.add_job.call_count, 3)
        for call in scheduler.add_job.call_args_list:
            self.assertEqual(call.kwargs["trigger"], "interval")
            self.assertEqual(call.kwargs["minutes"], 1)
            self.assertTrue(call.kwargs["coalesce"])
            self.assertEqual(call.kwargs["max_instances"], 1)
        scheduler.start.assert_called_once_with()

    def test_encryption_documentation_matches_storage_model(self):
        claude = Path("CLAUDE.md").read_text()
        finance_page = Path("frontend/pages/finance.html").read_text()

        self.assertIn("Asset balance amounts are encrypted", claude)
        self.assertIn("Transaction amounts and finance-goal amounts remain", claude)
        self.assertNotIn("Transaction and asset amounts are encrypted", claude)
        self.assertNotIn("your data is encrypted and yours alone", finance_page)


if __name__ == "__main__":
    unittest.main()
