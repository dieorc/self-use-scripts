import hashlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile


SOURCE = (Path(__file__).resolve().parents[1] / 'bootstrap.sh').read_text(encoding='utf-8')
EXTRACTOR = SOURCE.split("<<'PY_BOOTSTRAP'\n", 1)[1].split('\nPY_BOOTSTRAP\n', 1)[0]
MODULE = {'__name__': 'bootstrap_extractor'}
exec(compile(EXTRACTOR, 'bootstrap.sh:extractor', 'exec'), MODULE)


class BootstrapTests(unittest.TestCase):
    def archive(self, transform=None):
        files = {p: b'test-content' for p in ('oneclick.sh', 'install.sh', 'snell_quota.py', 'manage.sh',
                 'psm-snell', 'systemd/psm-snell-quota.service', 'systemd/psmq-snell@.service')}
        files['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + path + '\n'
                                     for path, data in files.items()).encode()
        if transform:
            transform(files)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            for path, body in files.items():
                info = zipfile.ZipInfo('project-main/' + path)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                z.writestr(info, body)
        data.seek(0)
        return data

    def test_valid_complete_archive(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / 'source'
            MODULE['extract_archive'](self.archive(), dest)
            self.assertEqual((dest / 'oneclick.sh').read_bytes(), b'test-content')

    def reject(self, archive, **options):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / 'source'
            with self.assertRaises(ValueError):
                MODULE['extract_archive'](archive, dest, **options)
            self.assertFalse(dest.exists())

    def test_path_traversal_rejected(self):
        self.reject(self.archive(lambda f: f.update({'../escape': b'bad'})))

    def test_backslash_rejected(self):
        self.reject(self.archive(lambda f: f.update({'folder\\escape': b'bad'})))

    def test_checksum_mismatch_rejected(self):
        self.reject(self.archive(lambda f: f.update({'oneclick.sh': b'changed'})))

    def test_unlisted_script_rejected(self):
        self.reject(self.archive(lambda f: f.update({'extra.sh': b'bad'})))

    def test_missing_required_file_rejected(self):
        self.reject(self.archive(lambda f: f.pop('install.sh')))

    def test_size_limit_rejected(self):
        self.reject(self.archive(), max_bytes=10)

    def test_symlink_rejected(self):
        archive = self.archive()
        with zipfile.ZipFile(archive, 'a') as z:
            info = zipfile.ZipInfo('project-main/link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, '/etc/passwd')
        archive.seek(0)
        self.reject(archive)


if __name__ == '__main__':
    unittest.main()
