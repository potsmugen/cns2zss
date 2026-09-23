import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cns2zss_gui import CNS2ZSSApp


class CNS2ZSSGuiTest(unittest.TestCase):
    def test_cancel_stops_batch_after_current_file(self):
        app = CNS2ZSSApp.__new__(CNS2ZSSApp)
        app.cancel_event = threading.Event()
        app.root = Mock()
        app.log = Mock()

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.cns'
            second = Path(directory) / 'second.cns'
            first.write_text('first input', encoding='utf-8')
            second.write_text('second input', encoding='utf-8')

            def read_first_file(path):
                app.cancel_event.set()
                return 'input', 'utf-8'

            with patch(
                'cns2zss_gui.read_file_with_encoding',
                side_effect=read_first_file,
            ), patch(
                'cns2zss_gui.convert_cns_to_zss',
                return_value='converted output',
            ) as convert:
                app._convert_worker([str(first), str(second)])

            self.assertEqual(convert.call_count, 1)
            self.assertEqual(
                Path(str(first) + '.zss').read_text(encoding='utf-8'),
                'converted output',
            )
            self.assertFalse(Path(str(second) + '.zss').exists())

        callback_args = app.root.after.call_args.args
        self.assertEqual(callback_args[1], app._convert_done)
        self.assertEqual(callback_args[2:], (1, 0, 0, 2, True))

    def test_batch_summary_counts_converted_skipped_and_failed(self):
        app = CNS2ZSSApp.__new__(CNS2ZSSApp)
        app.cancel_event = threading.Event()
        app.root = Mock()
        app.log = Mock()

        with tempfile.TemporaryDirectory() as directory:
            paths = [
                str(Path(directory) / name)
                for name in ('converted.cns', 'skipped.cns', 'failed.cns')
            ]

            def read_input(path):
                return Path(path).stem, 'utf-8'

            def convert_input(content):
                if content == 'skipped':
                    return '(NO_STATEDDEF)'
                if content == 'failed':
                    raise ValueError('invalid input')
                return 'converted output'

            with patch(
                'cns2zss_gui.read_file_with_encoding',
                side_effect=read_input,
            ), patch(
                'cns2zss_gui.convert_cns_to_zss',
                side_effect=convert_input,
            ):
                app._convert_worker(paths)

            self.assertTrue(Path(paths[0] + '.zss').exists())
            self.assertFalse(Path(paths[1] + '.zss').exists())
            self.assertFalse(Path(paths[2] + '.zss').exists())

        callback_args = app.root.after.call_args.args[2:]
        self.assertEqual(callback_args, (1, 1, 1, 3, False))

        app.conversion_active = True
        app.worker_thread = Mock()
        app.convert_sel_btn = Mock()
        app.convert_all_btn = Mock()
        app.cancel_btn = Mock()
        app.close_when_done = False
        app._convert_done(*callback_args)
        self.assertEqual(
            app.log.call_args.args[0],
            'Done. Converted: 1; skipped: 1; failed: 1 (of 3 file(s)).',
        )

    def test_close_waits_for_cancelled_batch_to_finish(self):
        app = CNS2ZSSApp.__new__(CNS2ZSSApp)
        app.cancel_event = threading.Event()
        app.conversion_active = True
        app.worker_thread = None
        app.close_when_done = False
        app.root = Mock()
        app.cancel_btn = Mock()

        with patch('cns2zss_gui.messagebox.askyesno', return_value=True):
            app.on_close()

        self.assertTrue(app.cancel_event.is_set())
        self.assertTrue(app.close_when_done)
        app.root.destroy.assert_not_called()

        app.log = Mock()
        app.worker_thread = Mock()
        app.convert_sel_btn = Mock()
        app.convert_all_btn = Mock()
        app._convert_done(0, 0, 0, 2, True)

        app.root.destroy.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
