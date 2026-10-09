import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("namer", ROOT / "scripts/namer.py")
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)
ispec = importlib.util.spec_from_file_location("namer_install", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(ispec)
ispec.loader.exec_module(installer)


class Tests(unittest.TestCase):
    def setUp(self):
        self.cfg = n.config()
        self.cfg["enabled"] = True
        self.cfg["project_patterns"] = {"ExampleApp": "exampleapp|示例应用"}
        self.config_patch = patch.object(n, "config", return_value=self.cfg)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def test_initial_content_does_not_require_keywords_or_length(self):
        for request in ["如何安装？", "排序", "你好", "你好，今天天气怎么样？", "Help", "π"]:
            with self.subTest(request=request):
                self.assertIsNone(n.gate({}, [request], self.cfg, 2000))
        cleaned = n.clean_user("```text\n" + "action=999\n" * 50 + "```")
        self.assertIsNone(n.gate({}, [cleaned], self.cfg, 2000))
        self.assertEqual(n.gate({}, [" ", ""], self.cfg, 2000), "no_new_content")

    def test_only_message_count_triggers_reevaluation(self):
        state = {"auto_title": "old", "consumed": 1}
        users = ["原请求"] + ["补充需求" for _ in range(10)]
        with patch.object(n, "signature", side_effect=AssertionError("not a trigger")):
            for count in range(1, 10):
                self.assertEqual(n.gate(state, users[:count + 1], self.cfg, 2000), "awaiting_more_context")
            self.assertIsNone(n.gate(state, users, self.cfg, 2000))
            self.assertEqual(n.gate(state, ["原请求", "新主题与更多细节" * 1000], self.cfg, 2000),
                             "awaiting_more_context")

    def test_cooldown_retains_pending(self):
        state = {"auto_title": "old", "consumed": 1, "last_attempt": 1500}
        users = ["第一轮"] + ["新增内容"] * 10
        self.assertEqual(n.gate(state, users, self.cfg, 1600), "cooldown")
        self.assertIsNone(n.gate(state, users, self.cfg, 2200))
        self.assertEqual(state["consumed"], 1)

    def test_custom_threshold_and_old_config_defaults(self):
        state = {"auto_title": "old", "consumed": 1}
        cfg = {k: v for k, v in self.cfg.items() if not k.startswith("reevaluate_")}
        self.assertEqual(n.gate(state, ["old"] + ["a"] * 9, cfg, 2000), "awaiting_more_context")
        self.assertIsNone(n.gate(state, ["old"] + ["a"] * 10, cfg, 2000))
        # An obsolete character threshold in an existing install has no effect.
        cfg.update(reevaluate_after_messages=2, reevaluate_after_chars=1)
        self.assertIsNone(n.gate(state, ["old", "a", "b"], cfg, 2000))
        self.assertEqual(n.gate(state, ["old", "0123456789" * 100], cfg, 2000), "awaiting_more_context")

    def test_manual_lock(self):
        self.assertEqual(n.gate({"locked": True}, ["new"], self.cfg, 2000), "manual_title_locked")

    def test_title_validation(self):
        result = dict(project="ExampleApp", topic="问题排查", subject="错误排查与输入校验", summary="test")
        title = n.format_title(result, "2026-09-29", self.cfg)
        self.assertEqual(title, "ExampleApp｜问题排查｜错误排查与输入校验｜2026-09-29")
        result["subject"] = "已修复错误"
        with self.assertRaises(ValueError):
            n.format_title(result, "2026-09-29", self.cfg)

    def test_approval_and_wrong_session_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); (base / "sessions").mkdir()
            f = base / "sessions" / "test.jsonl"
            rows = [{"type": "session_meta", "payload": {"id": "abc", "source": "vscode"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": ">>> TRANSCRIPT START"}]}}]
            f.write_text("\n".join(map(json.dumps, rows)))
            with patch.object(n, "CODEX", base):
                self.assertIsNone(n.transcript(f, "abc"))

    def test_manual_change_prevents_model_call(self):
        class FakeRpc:
            def read(self, tid): return {"name": "用户自定义标题"}
            def close(self): pass
            def infer(self, *args): raise AssertionError("must not call model")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(n, "DATA", Path(directory)):
                c = n.db()
                n.save(c, "abc", {"auto_title": "旧自动标题", "tags": [], "consumed": 0})
                c.close()
                content = {"meta": {"timestamp": "2026-09-29T12:00:00Z"},
                           "users": ["ExampleApp 报错了，需要排查错误并补充测试"] * 10, "final": ""}
                with patch.object(n, "transcript", return_value=content), patch.object(n, "Rpc", FakeRpc):
                    result = n.process({"session_id": "abc", "transcript_path": "fake", "turn_id": "turn2"})
                self.assertEqual(result["reason"], "manual_title_locked")
                c = n.db()
                self.assertEqual(c.execute("SELECT count(*) FROM calls").fetchone()[0], 0)
                c.close()

    def test_daily_budget_prevents_model_call(self):
        class FakeRpc:
            def read(self, tid): return {"name": "default"}
            def close(self): pass
            def infer(self, *args): raise AssertionError("must not call model")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(n, "DATA", Path(directory)):
                c = n.db()
                day = n.dt.datetime.now(n.ZoneInfo(self.cfg["timezone"])).date().isoformat()
                for _ in range(self.cfg["daily_model_calls"]):
                    c.execute("INSERT INTO calls(day,status) VALUES(?,?)", (day,"failed"))
                c.commit(); c.close()
                content = {"meta": {"timestamp": "2026-09-29T12:00:00Z"},
                           "users": ["ExampleApp 报错了，需要排查错误并补充测试"], "final": ""}
                with patch.object(n, "transcript", return_value=content), patch.object(n, "Rpc", FakeRpc):
                    result = n.process({"session_id": "abc", "transcript_path": "fake"})
                self.assertEqual(result["reason"], "daily_limit")

    def test_disabled_never_reads_or_calls(self):
        self.cfg["enabled"] = False
        with patch.object(n, "transcript", side_effect=AssertionError("must not read")):
            self.assertEqual(n.process({})["action"], "skipped")

    def test_full_rename_and_duplicate_without_second_call(self):
        class FakeRpc:
            title = "默认标题"
            calls = 0
            def read(self, tid): return {"name": self.title}
            def name(self, tid, title): self.title = title; FakeRpc.title = title
            def close(self): pass
            def infer(self, *args):
                FakeRpc.calls += 1
                return dict(project="ExampleApp",topic="问题排查",subject="错误排查与输入校验",summary="输入校验设计"), {"total":{"totalTokens":100}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(n, "DATA", Path(directory)):
                content = {"meta": {"timestamp": "2026-09-29T12:00:00Z"},
                           "users": ["ExampleApp 报错了，需要排查错误并补充测试"], "final": ""}
                payload = {"session_id":"abc","transcript_path":"fake","turn_id":"turn1"}
                with patch.object(n, "transcript", return_value=content), patch.object(n, "Rpc", FakeRpc):
                    result = n.process(payload)
                    repeated = n.process(payload)
                self.assertEqual(result["action"], "renamed")
                self.assertEqual(repeated["reason"], "duplicate_turn")
                self.assertEqual(FakeRpc.calls, 1)
                c=n.db()
                record=c.execute("SELECT usage FROM calls").fetchone()[0]
                self.assertEqual(json.loads(record)["total"]["totalTokens"],100)
                state=json.loads(c.execute("SELECT value FROM threads").fetchone()[0])
                self.assertEqual(state["original_title"],"默认标题")
                c.close()

    def test_custom_project_patterns(self):
        self.cfg["project_patterns"] = {"ExampleApp": "exampleapp|示例应用"}
        self.assertIn("ExampleApp", n.signature("检查示例应用配置"))

    def test_portable_install_paths_and_idempotence(self):
        import shlex
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target, codex_home = base / "user tools" / "namer", base / "custom codex"
            codex_home.mkdir()
            unrelated = {"type": "command", "command": "echo other-hook"}
            (codex_home / "hooks.json").write_text(json.dumps({"hooks":{"Stop":[{"hooks":[unrelated]}]}}))
            first = installer.install(ROOT, target, codex_home, check=False)
            args = shlex.split(first["hook_command"])
            self.assertIn("CODEX_HOME=" + str(codex_home), args)
            self.assertIn(str(target / "scripts/namer.py"), args)
            self.assertFalse((target / "data").exists())
            cfg = json.loads((target / "config/config.json").read_text())
            self.assertFalse(cfg["enabled"])
            cfg["cooldown_seconds"] = 1234
            (target / "config/config.json").write_text(json.dumps(cfg))
            second = installer.install(ROOT, target, codex_home, check=False)
            hooks = json.loads((codex_home / "hooks.json").read_text())
            handlers = [h for g in hooks["hooks"]["Stop"] for h in g["hooks"]]
            self.assertIn(unrelated, handlers)
            self.assertEqual(sum(h["command"] == second["hook_command"] for h in handlers), 1)
            self.assertEqual(json.loads((target / "config/config.json").read_text())["cooldown_seconds"], 1234)
            self.assertTrue(Path(second["hooks_backup"]).exists())

    def test_installer_rejects_syntax_error_before_writing(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            for name in installer.FILES:
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, source / name)
            (source / "scripts/namer.py").write_text("import time accidental words\n")
            target, codex_home = base / "target", base / "codex"
            with self.assertRaises(SyntaxError):
                installer.install(source, target, codex_home, check=False)
            self.assertFalse(target.exists())
            self.assertFalse(codex_home.exists())

    def test_enable_and_disable_commands(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config").mkdir()
            with patch.object(n, "ROOT", Path(directory)), contextlib.redirect_stdout(io.StringIO()):
                for command, enabled in [("enable", True), ("disable", False)]:
                    with patch.object(n.sys, "argv", ["namer.py", command]):
                        self.assertEqual(n.main(), 0)
                    cfg=json.loads((Path(directory)/"config/config.json").read_text())
                    self.assertEqual(cfg["enabled"],enabled)

    def test_doctor_reports_hook_trust(self):
        import contextlib
        import io
        class FakeRpc:
            def request(self, method, params):
                return {"data":[{"hooks":[{"command":str(ROOT/"scripts/namer.py")+" hook", "enabled":True,
                                            "trustStatus":"trusted","eventName":"stop"}]}]}
            def close(self): pass
        output=io.StringIO()
        with patch.object(n,"Rpc",FakeRpc), patch.object(n.sys,"argv",["namer.py","doctor"]), contextlib.redirect_stdout(output):
            self.assertEqual(n.main(),0)
        self.assertTrue(json.loads(output.getvalue())["ready"])


class LifecycleTests(unittest.TestCase):
    """Exercise successive Stop events using real transcripts and SQLite state."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        (self.base / "sessions").mkdir()
        self.path = self.base / "sessions" / "conversation.jsonl"
        self.rows = [{"type": "session_meta", "payload": {
            "id": "conversation", "source": "cli", "timestamp": "2026-01-15T08:00:00Z"}}]
        self.cfg = {**n.config(), "enabled": True, "cooldown_seconds": 600,
                    "daily_model_calls": 500, "reevaluate_after_messages": 10}
        self.now = 2000
        self.turn = 0
        self.prompts = []
        self.writes = []
        self.title = "默认标题"
        self.result = dict(project="ExampleApp", topic="功能开发", subject="界面规划", summary="初步规划")
        self.error = None
        owner = self

        class FakeRpc:
            def read(self, tid):
                return {"name": owner.title}

            def name(self, tid, title):
                owner.writes.append(title)
                owner.title = title

            def infer(self, prompt, timeout):
                owner.prompts.append(json.loads(prompt))
                if owner.error:
                    raise owner.error
                return owner.result, {"total": {"totalTokens": 100}}

            def close(self):
                pass

        for name, value in [("CODEX", self.base), ("DATA", self.base / "data"),
                            ("config", lambda: self.cfg), ("Rpc", FakeRpc)]:
            patcher = patch.object(n, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(n.time, "time", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Test processes can themselves be launched under a naming environment.
        patcher = patch.dict(n.os.environ, {"CONVERSATION_NAMER_ACTIVE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def append_turn(self, request, reply="收到当前需求"):
        self.turn += 1
        for role, text in [("user", request), ("assistant", reply)]:
            self.rows.append({"type": "response_item", "payload": {
                "type": "message", "role": role, "phase": "final" if role == "assistant" else None,
                "content": [{"type": "text", "text": text}]}})
        self.path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in self.rows))

    def stop(self):
        return n.process({"session_id": "conversation", "transcript_path": str(self.path),
                          "turn_id": str(self.turn)})

    def state(self):
        c = n.db()
        try:
            row = c.execute("SELECT value FROM threads WHERE id='conversation'").fetchone()
            return json.loads(row[0]) if row else {}
        finally:
            c.close()

    def test_initial_then_same_topic_growth_then_unchanged_checkpoint(self):
        self.append_turn("做个界面")
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(self.state()["consumed"], 1)
        self.now += 600
        for request in ["主要给访客用", "手机上也要能看"] + ["补充页面细节"] * 7:
            self.append_turn(request)
            self.assertEqual(self.stop()["reason"], "awaiting_more_context")
        self.assertEqual(self.state()["consumed"], 1)
        self.append_turn("文字最好再大一点", "整理为移动端访客页面需求")
        self.result = {**self.result, "subject": "移动端访客页面与大字布局", "summary": "移动端访客需求"}
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(self.prompts[1]["previous_summary"], "初步规划")
        self.assertEqual(self.prompts[1]["first_request"], "做个界面")
        self.assertIn("主要给访客用", self.prompts[1]["new_user_messages"])
        self.assertIn("移动端访客页面", self.prompts[1]["latest_result"])
        self.assertEqual(self.state()["date"], "2026-01-15")

        self.now += 600
        for request in ["继续", "好的"] * 5:
            self.append_turn(request)
        self.result = {**self.result, "summary": "继续讨论，标题仍准确"}
        self.assertEqual(self.stop()["action"], "unchanged")
        self.assertEqual(self.state()["consumed"], 21)
        self.assertEqual(self.state()["summary"], "继续讨论，标题仍准确")
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(self.stop()["reason"], "duplicate_turn")
        self.assertEqual(len(self.prompts), 3)
        self.now += 600
        for _ in range(9):
            self.append_turn("继续补充")
            self.assertEqual(self.stop()["reason"], "awaiting_more_context")
        self.assertEqual(len(self.prompts), 3)
        self.append_turn("最后一条补充")
        self.assertEqual(self.stop()["action"], "unchanged")
        self.assertEqual(self.state()["consumed"], 31)
        self.assertEqual(len(self.prompts), 4)

    def test_cooldown_and_failure_retry_keep_all_pending_content(self):
        self.append_turn("做个界面")
        self.stop()
        for _ in range(10):
            self.append_turn("页面面向来访者，需要把入口、提示和导航分别放在容易看到的位置。")
        self.now += 100
        self.assertEqual(self.stop()["reason"], "cooldown")
        self.assertEqual(self.state()["consumed"], 1)
        self.now += 500
        self.error = TimeoutError("simulated")
        with self.assertRaises(TimeoutError):
            self.stop()
        self.assertEqual(self.state()["consumed"], 1)
        self.assertEqual(self.stop()["reason"], "cooldown")
        self.now += 600
        self.error = None
        self.result = {**self.result, "subject": "访客入口与导航布局"}
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(self.prompts[-1]["new_user_messages"], self.prompts[-2]["new_user_messages"])
        self.assertEqual(self.state()["consumed"], 11)
        c = n.db()
        try:
            self.assertEqual([r[0] for r in c.execute("SELECT status FROM calls ORDER BY id")],
                             ["completed", "failed", "completed"])
        finally:
            c.close()

    def test_long_initial_request_survives_transcript_extraction(self):
        self.append_turn("页面应展示各个入口的说明，方便初次来访的人理解。" * 80)
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertTrue(self.prompts[0]["first_request"])
        self.assertEqual(self.state()["consumed"], 1)

    def test_page_metadata_is_removed_without_losing_user_request(self):
        metadata = '<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>'
        self.append_turn(metadata)
        self.assertEqual(self.stop()["reason"], "internal_or_empty")
        self.assertEqual(len(self.prompts), 0)
        self.append_turn(metadata + "\n今天是星期几？")
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(self.state()["consumed"], 1)
        self.assertEqual(self.prompts[0]["first_request"], "今天是星期几？")
        self.assertNotIn("external_codex", self.prompts[0]["new_user_messages"])
        self.now += 600
        for _ in range(9):
            self.append_turn(metadata)
            self.append_turn("继续")
            self.assertEqual(self.stop()["reason"], "awaiting_more_context")
        self.assertEqual(len(self.prompts), 1)
        self.append_turn("再说明一下")
        self.assertEqual(self.stop()["action"], "unchanged")
        self.assertEqual(self.state()["consumed"], 11)

    def test_legacy_checkpoint_migrates_once_before_duplicate_check(self):
        metadata = '<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>'
        self.append_turn(metadata)
        self.append_turn("今天是星期几？")
        c = n.db()
        try:
            n.save(c, "conversation", {"auto_title": self.title, "consumed": 2,
                                      "last_turn": str(self.turn), "summary": "旧摘要"})
        finally:
            c.close()
        self.assertEqual(self.stop()["reason"], "duplicate_turn")
        self.assertEqual(self.state()["consumed"], 1)
        self.assertEqual(self.state()["message_count_version"], 2)
        self.assertEqual(self.stop()["reason"], "duplicate_turn")
        self.assertEqual(self.state()["consumed"], 1)
        for _ in range(9):
            self.append_turn(metadata)
            self.append_turn("继续")
            self.assertEqual(self.stop()["reason"], "awaiting_more_context")
        self.append_turn("第十条补充")
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(self.state()["consumed"], 11)
        self.assertEqual(self.prompts[0]["previous_summary"], "旧摘要")

    def test_budget_does_not_consume_growth(self):
        self.cfg["daily_model_calls"] = 1
        self.append_turn("做个界面")
        self.stop()
        self.now += 600
        for request in ["主要给访客用", "手机上也要能看", "文字最好再大一点"] + ["补充页面细节"] * 7:
            self.append_turn(request)
        self.assertEqual(self.stop()["reason"], "daily_limit")
        self.assertEqual(self.state()["consumed"], 1)
        self.assertEqual(len(self.prompts), 1)
        self.cfg["daily_model_calls"] = 2
        self.result = {**self.result, "subject": "移动端访客页面"}
        self.assertEqual(self.stop()["action"], "renamed")
        self.assertEqual(self.state()["consumed"], 11)

    def test_manual_title_is_preserved_when_growth_is_due(self):
        self.append_turn("做个界面")
        self.stop()
        self.title = "手动命名"
        self.now += 600
        for request in ["主要给访客用", "手机上也要能看", "文字最好再大一点"] + ["补充页面细节"] * 7:
            self.append_turn(request)
        self.assertEqual(self.stop()["reason"], "manual_title_locked")
        self.assertTrue(self.state()["locked"])
        self.assertEqual(self.title, "手动命名")
        self.assertEqual(len(self.prompts), 1)

    def test_hook_entrypoint_records_progress_and_contains_errors(self):
        import contextlib
        import io
        self.append_turn("排序")
        payload = {"session_id": "conversation", "transcript_path": str(self.path), "turn_id": "1"}
        def invoke(raw):
            output = io.StringIO()
            with patch.object(n.sys, "argv", ["namer.py", "hook"]), \
                    patch.object(n.sys, "stdin", io.StringIO(raw)), contextlib.redirect_stdout(output):
                self.assertEqual(n.main(), 0)
            self.assertEqual(output.getvalue().strip(), "{}")
        invoke(json.dumps(payload))
        self.assertEqual(self.state()["consumed"], 1)
        c = n.db()
        try:
            kinds = [r[0] for r in c.execute("SELECT kind FROM events ORDER BY id")]
            self.assertIn("hook_received", kinds)
            self.assertIn("hook_result", kinds)
        finally:
            c.close()
        invoke("{invalid json")
        invoke("[]")
        # Failure to write diagnostics must not escape or suppress processing.
        with patch.object(n, "db", side_effect=OSError("read-only directory")), \
                patch.object(n, "process", return_value={"action": "skipped"}) as process:
            invoke(json.dumps(payload))
            process.assert_called_once()

    def test_initial_model_failure_retries_and_unlock_reuses_content(self):
        self.append_turn("排序")
        self.error = TimeoutError("simulated")
        with self.assertRaises(TimeoutError):
            self.stop()
        self.assertFalse(self.state().get("auto_title"))
        self.now += 600
        self.error = None
        self.assertEqual(self.stop()["action"], "renamed")
        import contextlib
        import io
        with patch.object(n.sys, "argv", ["namer.py", "unlock", "--thread", "conversation"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(n.main(), 0)
        self.now += 600
        self.assertEqual(self.stop()["action"], "unchanged")
        self.assertEqual(self.prompts[-1]["new_user_messages"], "排序")


if __name__ == "__main__":
    unittest.main()
