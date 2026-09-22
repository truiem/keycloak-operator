"""Test event routing and immutable artifact/source boundaries without network access."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('image_publication', Path(__file__).parents[2] / '.github/actions/image-publication/validate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = 'a' * 40


class API:
    def __init__(self):
        self.run = dict(id=123, repository={'id': 1}, head_repository={'id': 1},
                        status='completed', conclusion='success', path='.github/workflows/ci.yml',
                        head_sha=SHA, head_branch='feature', run_attempt=1, event='pull_request')
        self.pulls = [dict(head={'sha': SHA, 'repo': {'id': 1}},
                           base={'repo': {'id': 1}, 'ref': 'main'})]
        self.artifacts = [dict(id=456, name='image', expired=False)]
        self.tag = {'type': 'commit', 'sha': SHA}

    def get(self, path):
        if path == 'actions/runs/123': return self.run
        if path.startswith('pulls?'): return self.pulls
        if '/artifacts?' in path: return {'artifacts': self.artifacts}
        if path.startswith('git/'): return {'object': self.tag}
        raise AssertionError(path)


class ImagePublicationTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.event = {'workflow_run': copy.deepcopy(self.api.run),
                      'repository': {'id': 1, 'owner': {'login': 'truiem'}, 'default_branch': 'main'}}

    def resolve(self, registry='ecr'):
        return module.resolve(self.api, self.event, registry, '.github/workflows/ci.yml', 'image')

    def test_pr_publishes_dev_and_ghcr_never_prod(self):
        for registry, environment in [('ecr', 'publish-ecr-dev'), ('ghcr', 'publish-ghcr')]:
            result = self.resolve(registry)
            self.assertEqual(result['environment'], environment)
            self.assertEqual(result['tag'], 'sha-aaaaaaa')
            self.assertEqual(result['artifact-id'], '456')

    def test_dependabot_dispatch_requires_current_pr(self):
        self.api.run['event'] = 'workflow_dispatch'
        self.assertEqual(self.resolve()['environment'], 'publish-ecr-dev')
        self.api.pulls = []
        self.assertEqual(self.resolve(), {})

    def test_tag_publishes_only_prod(self):
        self.api.run.update(event='push', head_branch='v1.2.3')
        self.assertEqual(self.resolve()['environment'], 'publish-ecr-prod')
        self.assertEqual(self.resolve()['tag'], '1.2.3')
        self.assertEqual(self.resolve('ghcr'), {})

    def test_main_push_does_not_publish(self):
        self.api.run.update(event='push', head_branch='main')
        self.assertEqual(self.resolve(), {})
        self.assertEqual(self.resolve('ghcr'), {})

    def test_reject_fork_and_other_workflow(self):
        self.api.run['head_repository']['id'] = 2
        with self.assertRaises(ValueError): self.resolve()
        self.api.run['head_repository']['id'] = 1
        self.api.run['path'] = '.github/workflows/evil.yml'
        with self.assertRaises(ValueError): self.resolve()

    def test_skip_failed_incomplete_superseded_runs(self):
        for field, value in [('conclusion', 'failure'), ('status', 'in_progress'), ('run_attempt', 2)]:
            with self.subTest(field=field):
                original = self.api.run[field]
                self.api.run[field] = value
                self.assertEqual(self.resolve(), {})
                self.api.run[field] = original

    def test_skip_closed_stale_wrong_base_or_ambiguous_pr(self):
        for pulls in [[], [dict(head={'sha': 'b' * 40, 'repo': {'id': 1}}, base={'repo': {'id': 1}, 'ref': 'main'})],
                      [dict(head={'sha': SHA, 'repo': {'id': 1}}, base={'repo': {'id': 1}, 'ref': 'other'})],
                      self.api.pulls * 2]:
            self.api.pulls = pulls
            self.assertEqual(self.resolve(), {})

    def test_reject_missing_expired_or_ambiguous_artifacts(self):
        original = copy.deepcopy(self.api.artifacts)
        for artifacts in [[], [dict(id=456, name='image', expired=True)], original * 2]:
            self.api.artifacts = artifacts
            with self.assertRaises(ValueError): self.resolve()

    def test_reject_moved_tag(self):
        self.api.run.update(event='push', head_branch='v1.2.3')
        self.api.tag['sha'] = 'b' * 40
        with self.assertRaises(ValueError): self.resolve()

    def test_reject_unexpected_sha(self):
        self.api.run['head_sha'] = 'b' * 40
        with self.assertRaises(ValueError): self.resolve()


if __name__ == '__main__': unittest.main()
