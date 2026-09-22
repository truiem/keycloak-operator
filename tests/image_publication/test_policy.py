"""Check image routes and keep publishing credentials out of build jobs."""
from pathlib import Path
import unittest
import yaml
EXPECTED_ARTIFACTS = ['image']
ROOT = Path(__file__).resolve().parents[2]

def read(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)

class ImagePublicationPolicy(unittest.TestCase):
    def test_trusted_followup_routes_every_image_to_both_registries(self):
        ci, publication = read('ci.yml'), read('publish-images.yml')
        self.assertEqual(publication['on'], {'workflow_run': {'workflows': [ci['name']], 'types': ['completed']}})
        routes = {}
        for name, job in publication['jobs'].items():
            if name == 'cleanup':
                continue
            self.assertNotIn('steps', job)
            self.assertNotIn('secrets', job)
            if job['uses'].startswith('truiem/'):
                self.assertRegex(job['uses'], r'^truiem/workflow-templates/\.github/workflows/publish-image-v2.yml@[0-9a-f]{40}$')
            else:
                self.assertEqual(job['uses'], './.github/workflows/publish-image-v2.yml')
            self.assertEqual(job['with']['build-workflow'], '.github/workflows/ci.yml')
            self.assertNotIn('environment', job['with'])  # Trusted validator selects dev vs prod.
            self.assertNotIn('image-tag', job['with'])    # PR content never chooses a production tag.
            routes.setdefault(job['with']['image-artifact'], set()).add(job['with']['registry'])
        self.assertEqual(set(routes), set(EXPECTED_ARTIFACTS))
        self.assertTrue(all(destinations == {'ecr', 'ghcr'} for destinations in routes.values()))

    def test_cleanup_waits_for_all_destinations(self):
        publication = read('publish-images.yml')
        cleanup = publication['jobs']['cleanup']
        self.assertEqual(set(cleanup['needs']), set(publication['jobs']) - {'cleanup'})
        self.assertNotIn('if', cleanup)  # Default success gating preserves artifacts after any failed push.
        self.assertEqual(cleanup['permissions'], {'actions': 'write'})
        self.assertEqual(set(cleanup['with']['artifact-names'].split()), set(EXPECTED_ARTIFACTS))
        self.assertIn('cleanup-images-v2.yml', cleanup['uses'])
        self.assertNotIn('secrets', cleanup)

    def test_build_workflow_cannot_push_images(self):
        ci = read('ci.yml')
        self.assertEqual(ci['permissions'], {'contents': 'read'})
        for name, job in ci['jobs'].items():
            self.assertNotIn('publish-image-v2', job.get('uses', ''))
            self.assertFalse(name.startswith('publish-'))
            self.assertNotIn('id-token', job.get('permissions', {}))
            self.assertNotEqual(job.get('permissions', {}).get('packages'), 'write')
            for step in job.get('steps', []):
                self.assertNotIn('configure-aws-credentials', step.get('uses', ''))
                self.assertNotIn('login-action', step.get('uses', ''))
                if 'build-push-action' in step.get('uses', ''):
                    self.assertEqual(step['with']['push'], 'false')
        self.assertIn('image-publication-policy', ci['jobs'])

if __name__ == '__main__': unittest.main()
