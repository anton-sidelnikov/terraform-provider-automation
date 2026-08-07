import subprocess
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
