import subprocess
import sys
import unittest
from pathlib import Path


class APITests(unittest.TestCase):
    def test_planning_api_does_not_import_copilot_runtime(self) -> None:
        subprocess.run(
            [
                sys.executable,
                "-c",
                'import sys, otc_agent.api; assert "copilot" not in sys.modules',
            ],
            check=True,
        )

    def test_planning_api_imports_without_site_packages(self) -> None:
        subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import otc_agent.api",
            ],
            check=True,
            env={"PYTHONPATH": str(Path("src").resolve())},
        )


if __name__ == "__main__":
    unittest.main()
