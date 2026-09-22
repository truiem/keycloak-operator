"""Guard credential boundaries after moving the repository."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class WorkflowBoundaries(unittest.TestCase):
    def test_no_legacy_credentials_or_shared_callers(self):
        for path in (ROOT / ".github/workflows").glob("*.y*ml"):
            content = path.read_text()
            for forbidden in ("secrets.PAT", "secrets: inherit", "permissions: write-all", "gulfcoastdevops/workflow-templates"):
                self.assertNotIn(forbidden, content, str(path))

    def test_public_fork_has_no_private_workflow_dependency(self):
        content = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertNotIn("truiem/workflow-templates/", content)
        self.assertNotIn("secrets: inherit", content)
        self.assertNotIn("persist-credentials: true", content)
