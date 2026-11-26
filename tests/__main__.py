"""Run application regressions; no live NASA or paid Cloud pilot is started."""
import argparse
import gc
from pathlib import Path
import unittest


class MainThreadResult(unittest.TextTestResult):
    """Collect Tk objects on the UI thread, not inside a later worker test."""
    def stopTest(self, test):
        super().stopTest(test)
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gdal-python', type=Path, help='Optional GDAL Python for raster regressions')
    parser.add_argument('tests', nargs='*', help='Optional unittest module names')
    args = parser.parse_args()
    if args.gdal_python:
        if not args.gdal_python.is_file():
            parser.error('GDAL Python does not exist')
        import swotflow.core.gdal as runtime
        runtime.DEFAULT_GDAL_PYTHON = args.gdal_python.resolve()
    gc.disable()
    suite = (unittest.defaultTestLoader.loadTestsFromNames(args.tests) if args.tests else
             unittest.defaultTestLoader.discover(str(Path(__file__).parent)))
    result = unittest.TextTestRunner(verbosity=2, resultclass=MainThreadResult).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
