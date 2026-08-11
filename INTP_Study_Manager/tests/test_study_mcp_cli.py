from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from study_mcp import server


class StudyMcpCliTest(unittest.TestCase):
    def test_cli_supports_only_local_stdio_and_explicit_user_binding(self):
        args = server.build_parser().parse_args(
            ["--transport", "stdio", "--user-id", "17"]
        )
        self.assertEqual(args.transport, "stdio")
        self.assertEqual(args.user_id, 17)
        with self.assertRaises(SystemExit):
            server.build_parser().parse_args(["--transport", "http"])
        with self.assertRaises(SystemExit):
            server.build_parser().parse_args(["--user-id", "-1"])
        with self.assertRaises(SystemExit):
            server.build_parser().parse_args(["--transport", "stdio"])

    def test_main_records_runtime_status_around_server_process(self):
        fake_server = Mock()
        with (
            patch.object(server, "create_server", return_value=fake_server) as create,
            patch.object(server, "mcp_runtime_status_service") as status,
        ):
            exit_code = server.main(["--transport", "stdio", "--user-id", "17"])

        self.assertEqual(exit_code, 0)
        create.assert_called_once_with(17)
        status.mark_runtime_started.assert_called_once_with(17, transport="stdio")
        fake_server.run.assert_called_once_with(transport="stdio")
        status.mark_runtime_stopped.assert_called_once_with(17)

    def test_runtime_is_marked_stopped_when_protocol_loop_raises(self):
        fake_server = Mock()
        fake_server.run.side_effect = RuntimeError("transport stopped")
        with (
            patch.object(server, "create_server", return_value=fake_server),
            patch.object(server, "mcp_runtime_status_service") as status,
        ):
            with self.assertRaisesRegex(RuntimeError, "transport stopped"):
                server.main(["--user-id", "3"])

        status.mark_runtime_started.assert_called_once_with(3, transport="stdio")
        status.mark_runtime_stopped.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
