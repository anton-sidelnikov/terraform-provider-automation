import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otc_agent.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_loads_env_file_without_overriding_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "export OTC_MODEL_NAME=from-file\n"
                "OTC_POSTGRES_DSN='postgresql://db/agent'\n"
                'OTC_QUOTED_VALUE="line\\nvalue"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OTC_MODEL_NAME": "from-process"}, clear=True):
                loaded = load_environment(path)

                self.assertEqual(loaded, path.resolve())
                self.assertEqual(os.environ["OTC_MODEL_NAME"], "from-process")
                self.assertEqual(os.environ["OTC_POSTGRES_DSN"], "postgresql://db/agent")
                self.assertEqual(os.environ["OTC_QUOTED_VALUE"], "line\nvalue")
