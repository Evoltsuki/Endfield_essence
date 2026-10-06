import tempfile
import unittest
from pathlib import Path
from utils.session_log import SessionLog
from utils.log_retention import prune_logs


class LogRetentionTests(unittest.TestCase):
    def test_only_latest_five_sessions_remain_and_unrelated_files_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            personal = base/'config.json'
            personal.write_text('personal settings', encoding='utf8')
            sessions = []
            for _ in range(7):
                log = SessionLog(base)
                sessions.append(log.directory)
                log.close()
            self.assertEqual({p for p in base.iterdir() if p.is_dir()}, set(sessions[-5:]))
            self.assertEqual(personal.read_text(encoding='utf8'), 'personal settings')

    def test_active_old_log_keeps_its_entire_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            log = SessionLog(folder)
            log.begin_scan({})
            scan = log.scan_directory
            prune_logs(folder, keep=0)
            self.assertTrue((scan/'summary.json').exists())
            self.assertTrue((log.directory/'app.log').exists())
            log.close()
