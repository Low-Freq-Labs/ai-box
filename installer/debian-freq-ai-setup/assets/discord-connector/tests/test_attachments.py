import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from freq_discord_core import attachment_extension, ConnectorError


class AttachmentTests(unittest.TestCase):
    def test_useful_text_types_and_utf8_bom(self):
        for suffix in ('.md', '.txt', '.log', '.csv', '.json', '.yaml', '.py', '.diff', '.svg', '.vtt'):
            self.assertEqual(attachment_extension(b'\xef\xbb\xbfhello\n', 'sample'+suffix), suffix)

    def test_utf16_bom_text_is_supported(self):
        self.assertEqual(attachment_extension('Notes café\n'.encode('utf-16'), 'notes.md'), '.md')

    def test_gif_pdf_zip(self):
        for data, name, expected in [(b'GIF89aframe', 'a.gif', '.gif'),
                                      (b'%PDF-1.7', 'a.pdf', '.pdf'),
                                      (b'PK\x03\x04data', 'a.zip', '.zip')]:
            self.assertEqual(attachment_extension(data, name), expected)

    def test_binary_spoof_unknown_empty_and_oversize_rejected(self):
        for data, name in [(b'MZ\x00bad', 'a.txt'), (b'bad', 'a.pdf'), (b'bad', 'a.zip'),
                            (b'x', 'a.exe'), (b'\xff\xfe\x00', 'a.md'), (b'', 'a.txt'),
                            (b'x'*(10*1024*1024+1), 'a.txt')]:
            with self.assertRaises(ConnectorError):
                attachment_extension(data, name)
