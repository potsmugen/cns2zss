import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cns2zss import (
    convert_cns_to_zss,
    read_file_with_encoding,
    write_file_atomically,
)


FIXTURES = Path(__file__).parent / 'fixtures'


class CNS2ZSSTest(unittest.TestCase):
    def test_comprehensive_fixture(self):
        source = (FIXTURES / 'comprehensive.cns').read_text(
            encoding='utf-8'
        )
        expected = (FIXTURES / 'comprehensive.zss').read_text(
            encoding='utf-8'
        )

        actual = convert_cns_to_zss(source)

        self.assertEqual(actual, expected)

    def test_no_statedef_returns_sentinel(self):
        source = '[Data]\nlife = 1000\n'

        self.assertEqual(
            convert_cns_to_zss(source),
            '(NO_STATEDDEF)',
        )

    def test_literal_plus_one_is_distinct_from_unsigned_one(self):
        source = (
            '[Statedef +1]\ntype = S\n'
            '[Statedef 1]\ntype = S\n'
            '[Statedef +1]\ntype = A\n'
        )

        output = convert_cns_to_zss(source)

        self.assertEqual(output.count('[StateDef +1;'), 1)
        self.assertEqual(output.count('[StateDef 1;'), 1)
        self.assertIn('# WARNING: Duplicate state +1 removed', output)

    def test_other_plus_prefixed_statedef_numbers_are_not_accepted(self):
        for number in ('+0', '+2', '+01'):
            with self.subTest(number=number):
                source = f'[Statedef {number}]\ntype = S\n'
                self.assertEqual(
                    convert_cns_to_zss(source),
                    '(NO_STATEDDEF)',
                )

    def test_atomic_write_leaves_existing_file_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.zss'
            path.write_text('original', encoding='utf-8')

            with (
                patch(
                    'cns2zss.os.replace',
                    side_effect=OSError('replace failed'),
                ),
                self.assertRaisesRegex(OSError, 'replace failed'),
            ):
                write_file_atomically(path, 'replacement')

            self.assertEqual(path.read_text(encoding='utf-8'), 'original')
            self.assertEqual(list(Path(directory).glob('.cns2zss-*.tmp')), [])

    def test_read_file_with_encoding_handles_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bom.cns'
            path.write_bytes('\ufeff[Statedef 0]'.encode('utf-8'))

            content, encoding = read_file_with_encoding(path)

        self.assertEqual(content, '[Statedef 0]')
        self.assertEqual(encoding, 'utf-8-sig')

    def test_read_file_with_encoding_handles_shift_jis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shift_jis.cns'
            path.write_bytes('日本語'.encode('shift_jis'))

            content, encoding = read_file_with_encoding(path)

        self.assertEqual(content, '日本語')
        self.assertEqual(encoding, 'shift_jis')


if __name__ == '__main__':
    unittest.main()
