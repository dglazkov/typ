# Copyright 2014 Dirk Pranke. All rights reserved.
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

import sys

# FIXME: make this work w/ python3.
from StringIO import StringIO


class FakeHost(object):
    # "too many instance attributes" pylint: disable=R0902
    # "redefining built-in" pylint: disable=W0622
    # "unused arg" pylint: disable=W0613

    python_interpreter = 'python'

    def __init__(self):
        self.stdin = StringIO()
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.sep = '/'
        self.dirs = set([])
        self.files = {}
        self.fetches = []
        self.fetch_responses = {}
        self.written_files = {}
        self.last_tmpdir = None
        self.current_tmpno = 0
        self.mtimes = {}
        self.cmds = []
        self.cwd = '/tmp'

    def abspath(self, *comps):
        relpath = self.join(*comps)
        if relpath.startswith('/'):
            return relpath
        return self.join(self.cwd, relpath)

    def add_to_path(self, *comps):
        absolute_path = self.abspath(*comps)
        if not absolute_path in sys.path:
            sys.path.append(absolute_path)

    def basename(self, path):
        return path.split(self.sep)[-1]

    def call(self, argv, stdin=None, env=None):
        self.cmds.append(argv)
        return 0, '', 'Python 2.7.5\n'

    def chdir(self, *comps):
        path = self.join(*comps)
        if not path.startswith('/'): # pragma: no cover
            path = self.join(self.cwd, path)
        self.cwd = path

    def cpu_count(self):
        return 1

    def dirname(self, path):
        return '/'.join(path.split('/')[:-1])

    def exists(self, *comps):
        path = self.abspath(*comps)
        return ((path in self.files and self.files[path] is not None) or
                path in self.dirs)

    def files_under(self, top):
        files = []
        for f in self.files:
            if self.files[f] is not None and f.startswith(top):
                files.append(self.relpath(f, top))
        return files

    def getcwd(self):
        return self.cwd

    def getenv(self, key, default=None):
        assert key
        return default

    def for_mp(self):
        return self

    def isdir(self, *comps):
        path = self.abspath(*comps)
        return path in self.dirs

    def isfile(self, *comps):
        path = self.abspath(*comps)
        return path in self.files and self.files[path] is not None

    def join(self, *comps):
        p = ''
        for c in comps:
            if c in ('', '.'): # pragma: no cover
                continue
            elif c.startswith('/'):
                p = c
            elif p:
                p += '/' + c
            else:
                p = c
        return p

    def maybe_mkdir(self, *comps):
        path = self.abspath(self.join(*comps))
        if not path in self.dirs:
            self.dirs.add(path)

    def mkdtemp(self, suffix='', prefix='tmp', dir=None, **_kwargs):
        if dir is None:
            dir = self.sep + '__im_tmp'
        curno = self.current_tmpno
        self.current_tmpno += 1
        self.last_tmpdir = self.join(dir, '%s_%u_%s' % (prefix, curno, suffix))
        self.dirs.add(self.last_tmpdir)
        return self.last_tmpdir

    def mtime(self, *comps):
        return self.mtimes.get(self.join(*comps), 0)

    def print_(self, msg='', end='\n', stream=None):
        stream = stream or self.stdout
        stream.write(str(msg) + end)
        stream.flush()

    def read_binary_file(self, *comps):
        return self._read(comps)

    def read_text_file(self, *comps):
        return self._read(comps)

    def _read(self, comps):
        return self.files[self.abspath(*comps)]

    def relpath(self, path, start):
        return path.replace(start + '/', '')

    def remove(self, *comps):
        path = self.abspath(*comps)
        self.files[path] = None
        self.written_files[path] = None

    def rmtree(self, *comps):
        path = self.abspath(*comps)
        for f in self.files:
            if f.startswith(path):
                self.files[f] = None
                self.written_files[f] = None
        self.dirs.remove(path)

    def terminal_width(self):
        return 80

    def splitext(self, path):
        idx = path.rfind('.')
        if idx == -1:
            return (path, '')
        return (path[:idx], path[idx:])

    def time(self):
        return 0

    def write_binary_file(self, path, contents):
        self._write(path, contents)

    def write_text_file(self, path, contents):
        self._write(path, contents)

    def _write(self, path, contents):
        full_path = self.abspath(path)
        self.maybe_mkdir(self.dirname(full_path))
        self.files[full_path] = contents
        self.written_files[full_path] = contents

    def fetch(self, url, data=None, headers=None): # pragma: no cover
        resp = self.fetch_responses.get(url, FakeResponse('', url))
        self.fetches.append((url, data, headers, resp))
        return resp


class FakeResponse(StringIO): # pragma: no cover
    def __init__(self, response, url, code=200):
        StringIO.__init__(self, response)
        self._url = url
        self.code = code

    def geturl(self):
        return self._url

    def getcode(self):
        return self.code