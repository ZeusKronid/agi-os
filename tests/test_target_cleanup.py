import sys,subprocess,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'archiso/airootfs/usr/local/share/agi-os/installer'))
import worker
from domain import ValidationError
class CleanupTests(unittest.TestCase):
    def test_stops_only_target_keyring_before_real_unmount(self):
        with tempfile.TemporaryDirectory() as d,patch.object(worker,'TARGET',Path(d)),patch('worker.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as run:
            (Path(d)/'etc/pacman.d/gnupg').mkdir(parents=True)
            worker.release_target()
            self.assertEqual([c.args[0] for c in run.call_args_list],[['gpgconf','--homedir',str(Path(d)/'etc/pacman.d/gnupg'),'--kill','all'],['umount','--recursive',d]])
    def test_failed_unmount_still_fails(self):
        with tempfile.TemporaryDirectory() as d,patch.object(worker,'TARGET',Path(d)),patch('worker.subprocess.run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaises(ValidationError):worker.release_target()
