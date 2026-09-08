import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cns2zss import convert_cns_to_zss


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


if __name__ == '__main__':
    unittest.main()
