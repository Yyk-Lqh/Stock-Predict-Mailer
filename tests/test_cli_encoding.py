"""Chinese help must survive redirected Windows pipes with legacy encodings."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from mcp_server import server


class ConsoleEncodingTests(unittest.TestCase):
    def test_chinese_help_is_utf8_even_with_a_western_pipe_encoding(self):
        commands = [["-m", name] for name in ("stock_predict_mailer", "mcp_server.server", "mcp_server.verify", "mcp_server.jobs_cli")]
        commands.append([str(Path(server.__file__))])
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, *command, "--help"],
                    env={**os.environ, "PYTHONIOENCODING": "cp1252"}, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                output = result.stdout.decode("utf-8")
                self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in output), output)
