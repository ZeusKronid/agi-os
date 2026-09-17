import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import deployment
import deploy_worker
from controller import DemoProvider
from domain import Configuration, ValidationError
from system import demo_inventory


class TransferReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / 'system.qcow2'
        self.image.write_bytes(b'preview')
        self.config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        self.snapshot = demo_inventory()
        self.snapshot.update(live=True, firmware='uefi')

    def test_source_change_invalidates_consent(self):
        with patch.object(deployment, 'target_inventory', return_value=self.snapshot):
            before = deployment.review(self.image, self.config, '/dev/vda')
            self.image.write_bytes(b'changed-preview')
            after = deployment.review(self.image, self.config, '/dev/vda')
        self.assertNotEqual(before['digest'], after['digest'])

    def test_target_identity_change_invalidates_consent(self):
        with patch.object(deployment, 'target_inventory', return_value=self.snapshot):
            before = deployment.review(self.image, self.config, '/dev/vda')
            self.snapshot['disks'][0]['fingerprint'] = 'replacement-disk'
            after = deployment.review(self.image, self.config, '/dev/vda')
        self.assertNotEqual(before['digest'], after['digest'])

    def test_busy_target_rejected(self):
        self.snapshot['disks'][0].update(eligible=False, reason='mounted')
        with patch.object(deployment, 'target_inventory', return_value=self.snapshot):
            with self.assertRaises(ValidationError):
                deployment.review(self.image, self.config, '/dev/vda')

    def test_worker_refuses_host_even_as_root(self):
        with patch.object(deploy_worker.os, 'geteuid', return_value=0), patch.object(deploy_worker, 'live_environment', return_value=False):
            with self.assertRaises(ValidationError):
                deploy_worker.checked_request({})

    def test_image_symlink_rejected(self):
        link = self.image.with_name('linked.qcow2')
        link.symlink_to(self.image)
        with self.assertRaises(ValidationError):
            deployment.image_identity(link)
