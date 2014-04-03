# Copyright 2014 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import inspect
import multiprocessing
import os
import pdb
import subprocess
import sys
import time
import unittest
import StringIO


from tpy_pool import make_pool
from tpy_stats import Stats
from tpy_printer import Printer


VERSION = '0.1'


def main(argv=None):
    started_time = time.time()

    args = parse_args(argv)
    if args.version:
        print_(VERSION)
        return 0
    if args.coverage:
        return run_under_coverage(argv)
    if args.debugger:
        args.jobs = 1
        args.pass_through = True

    stats = Stats(args.status_format, time.time, started_time)
    should_overwrite = sys.stdout.isatty() and not args.verbose
    printer = Printer(print_, should_overwrite)

    test_names = find_tests(args)
    if args.list_only:
        print_('\n'.join(sorted(test_names)))
        return 0
    return run_tests(args, printer, stats, test_names)


def parse_args(argv):
    ap = argparse.ArgumentParser()
    ap.usage = '%(prog)s [options] tests...'
    ap.add_argument('-c', dest='coverage', action='store_true',
                    help='produce coverage information')
    ap.add_argument('-d', dest='debugger', action='store_true',
                    help='run a single test under the debugger')
    ap.add_argument('-f', dest='file_list', action='store',
                    help=('take the list of tests from the file '
                          '(use "-" for stdin)'))
    ap.add_argument('-l', dest='list_only', action='store_true',
                    help='list all the test names found in the given tests')
    ap.add_argument('-j', metavar='N', type=int, dest='jobs',
                    default=multiprocessing.cpu_count(),
                    help=('run N jobs in parallel [default=%(default)s, '
                          'derived from CPUs available]'))
    ap.add_argument('-n', dest='dry_run', action='store_true',
                    help=('dry run (don\'t run commands but act like they '
                          'succeeded)'))
    ap.add_argument('-p', dest='pass_through', action='store_true',
                    help='pass output through while running tests')
    ap.add_argument('-q', action='store_true', dest='quiet', default=False,
                    help='be quiet (only print errors)')
    ap.add_argument('-s', dest='status_format',
                    default=os.getenv('NINJA_STATUS', '[%f/%t] '),
                    help=('format for status updates '
                          '(defaults to NINJA_STATUS env var if set, '
                          '"[%%f/%%t] " otherwise)'))
    ap.add_argument('-t', dest='timing', action='store_true',
                    help="print timing info")
    ap.add_argument('-v', action='count', dest='verbose', default=0,
                    help="verbose logging")
    ap.add_argument('-V', '--version', action='store_true',
                    help='print pytest version ("%s")' % VERSION)
    ap.add_argument('tests', nargs='*', default=[],
                    help=argparse.SUPPRESS)

    return ap.parse_args(argv)


def run_under_coverage(argv):
    argv = argv or sys.argv
    if '-c' in argv:
        argv.remove('-c')
    if '-j' in argv:
        argv.remove('-j')

    subprocess.call(['coverage', 'erase'])
    res = subprocess.call(['coverage', 'run', __file__] +
                          ['-j', '1'] + argv[1:])
    subprocess.call(['coverage', 'report', '--omit=*/pytest/*'])
    return res


def find_tests(args):
    loader = unittest.loader.TestLoader()
    test_names = []
    if args.file_list:
        if args.file_list == '-':
            f = sys.stdin
        else:
            f = open(args.file_list)
        tests = [line.strip() for line in f.readlines()]
        f.close()
    else:
        tests = args.tests

    for test in tests:
        if test.endswith('.py'):
            test = test.replace('/', '').replace('.py', '')
        module_suite = loader.loadTestsFromName(test)
        for suite in module_suite:
            if isinstance(suite, unittest.suite.TestSuite):
                test_names.extend(test_case.id() for test_case in suite)
            else:
                test_names.append(suite.id())
    return test_names


def run_tests(args, printer, stats, test_names):
    num_failures = 0
    running_jobs = set()
    stats.total = len(test_names)

    pool = make_pool(args.jobs, run_test, args)
    try:
        while test_names or running_jobs:
            while test_names and (len(running_jobs) < args.jobs):
                test_name = test_names.pop(0)
                stats.started += 1
                pool.send(test_name)
                running_jobs.add(test_name)
                print_test_started(printer, args, stats, test_name)

            test_name, res, out, err, took = pool.get()
            running_jobs.remove(test_name)
            if res:
                num_failures += 1
            stats.finished += 1
            print_test_finished(printer, args, stats, test_name,
                                res, out, err, took)
        pool.close()
    finally:
        pool.join()

    if not args.quiet:
        if args.timing:
            timing_clause = ' in %.4fs' % (time.time() - stats.started_time)
        else:
            timing_clause = ''
        printer.update('%d tests run%s, %d failure%s.' %
                       (stats.finished, timing_clause, num_failures,
                        '' if num_failures == 1 else 's'))
        print_()
    return 1 if num_failures > 0 else 0


def run_test(args, test_name):
    if args.dry_run:
        return test_name, 0, '', '', 0
    loader = unittest.loader.TestLoader()
    result = TestResult(pass_through=args.pass_through)
    suite = loader.loadTestsFromName(test_name)
    start = time.time()
    if args.debugger:
        test_case = suite._tests[0]
        test_func = getattr(test_case, test_case._testMethodName)
        fname = inspect.getsourcefile(test_func)
        lineno = inspect.getsourcelines(test_func)[1] + 1
        dbg = pdb.Pdb()
        dbg.set_break(fname, lineno)
        dbg.runcall(suite.run, result)
    else:
        suite.run(result)
    took = time.time() - start
    if result.failures:
        return (test_name, 1, result.out, result.err + result.failures[0][1],
                took)
    if result.errors:
        return (test_name, 1, result.out, result.err + result.errors[0][1],
                took)
    return (test_name, 0, result.out, result.err, took)


def print_test_started(printer, args, stats, test_name):
    if not args.quiet and printer.should_overwrite:
        printer.update(stats.format() + test_name, elide=(not args.verbose))


def print_test_finished(printer, args, stats, test_name, res, out, err, took):
    suffix = '%s%s%s' % (' failed' if res else ' passed',
                         (' %.4fs' % took) if args.timing else '',
                         (':\n' if (out or err) else ''))
    if res:
        printer.update(stats.format() + test_name + suffix, elide=False)
    elif not args.quiet or out or err:
        printer.update(stats.format() + test_name + suffix,
                       elide=(not out and not err and not args.verbose))
    for l in out.splitlines():
        print_('  %s' % l)
    for l in err.splitlines():
        print_('  %s' % l)


def print_(msg='', end='\n', stream=sys.stdout):
    stream.write(str(msg) + end)
    stream.flush()


class PassThrough(StringIO.StringIO):
    def __init__(self, stream=None):
        self.stream = stream
        StringIO.StringIO.__init__(self)

    def write(self, *args, **kwargs):
        if self.stream:
            self.stream.write(*args, **kwargs)
        StringIO.StringIO.write(self, *args, **kwargs)

    def flush(self, *args, **kwargs):
        if self.stream:
            self.stream.flush(*args, **kwargs)
        StringIO.StringIO.flush(self, *args, **kwargs)


class TestResult(unittest.TestResult):
    # unittests's TestResult has built-in support for buffering
    # stdout and stderr, but unfortunately it interacts awkwardly w/
    # the way they format errors (the output gets comingled and rearranged).
    def __init__(self, stream=None, descriptions=None, verbosity=None,
                 pass_through=False):
        self.pass_through = pass_through
        super(TestResult, self).__init__(stream=stream,
                                         descriptions=descriptions,
                                         verbosity=verbosity)
        self.out = ''
        self.err = ''
        self.__orig_out = None
        self.__orig_err = None

    # "Invalid name" pylint: disable=C0103

    def startTest(self, test):
        self.__orig_out = sys.stdout
        self.__orig_err = sys.stderr
        sys.stdout = PassThrough(sys.stdout if self.pass_through else None)
        sys.stderr = PassThrough(sys.stderr if self.pass_through else None)

    def stopTest(self, test):
        self.out = sys.stdout.getvalue()
        self.err = sys.stderr.getvalue()
        sys.stdout = self.__orig_out
        sys.stderr = self.__orig_err


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print >> sys.stderr, "Interrupted, exiting"
        sys.exit(130)