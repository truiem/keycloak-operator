"""Guard pre-merge QA publication and exact same-run artifact cleanup."""
from pathlib import Path
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[2]
EXPECTED = {'image': {'build': 'image', 'ecr': 'keycloak-operator', 'ghcr': 'keycloak-operator', 'prefix': ''}}
def read():return yaml.load((ROOT/'.github/workflows/ci.yml').read_text(),Loader=yaml.BaseLoader)
class PublicationPolicy(unittest.TestCase):
    def test_every_image_is_published_by_the_pr_run(self):
        d=read();self.assertIn('pull_request',d['on'])
        self.assertFalse((ROOT/'.github/workflows/publish-images.yml').exists())
        for artifact,image in EXPECTED.items():
            for target,registry,environment in [('dev','ecr','publish-ecr-dev'),('ghcr','ghcr','publish-ghcr'),('prod','ecr','publish-ecr-prod')]:
                job=d['jobs']['publish-'+artifact+'-'+target]
                self.assertIn(image['build'],job['needs'])
                self.assertEqual(job['with']['registry'],registry)
                self.assertEqual(job['with']['environment'],environment)
                self.assertEqual(job['with']['image-artifact'],artifact)
                self.assertEqual(job['with']['image-name'],image['ghcr'] if target=='ghcr' else image['ecr'])
                self.assertNotIn('steps',job);self.assertNotIn('secrets',job)
                if target=='prod':self.assertEqual(job['if'],"github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')")
                else:self.assertNotIn('if',job)
    def test_cleanup_requires_every_destination(self):
        jobs=read()['jobs'];job=jobs['cleanup-images'];pub={k for k in jobs if k.startswith('publish-')}
        self.assertEqual(set(job['needs']),pub)
        self.assertEqual(set(job['with']['artifact-names'].split()),set(EXPECTED))
        for name in pub:
            self.assertIn("needs['"+name+"'].result == 'success'",job['if'])
            if not name.endswith('-prod'):self.assertNotIn("needs['"+name+"'].result == 'skipped'",job['if'])
    def test_build_jobs_do_not_receive_registry_credentials(self):
        for name,job in read()['jobs'].items():
            if name.startswith('publish-') or name=='cleanup-images':continue
            self.assertNotIn('id-token',job.get('permissions',{}))
            self.assertNotEqual(job.get('permissions',{}).get('packages'),'write')
