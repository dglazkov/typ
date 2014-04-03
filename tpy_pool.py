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

import multiprocessing
import Queue


Empty = Queue.Empty  # "Invalid name" # pylint: disable=C0103


def make_pool(jobs, callback, usrp):
    if jobs > 1:
        return ProcessPool(jobs, callback, usrp)
    return AsyncPool(callback, usrp)


class ProcessPool(object):
    def __init__(self, jobs, callback, usrp):
        self.jobs = jobs
        self.requests = multiprocessing.Queue()
        self.responses = multiprocessing.Queue()
        self.workers = []
        self.closed = False
        for worker_num in range(jobs):
            w = multiprocessing.Process(target=_loop,
                                        args=(worker_num, callback, usrp,
                                              self.requests, self.responses))
            w.start()
            self.workers.append(w)

    def send(self, msg):
        self.requests.put((True, msg))

    def get(self, block=True, timeout=None):
        return self.responses.get(block, timeout)

    def close(self):
        for _ in self.workers:
            self.requests.put((False, None))
        self.requests.close()
        self.closed = True

    def join(self):
        if not self.closed:
            for w in self.workers:
                w.terminate()
        for w in self.workers:
            w.join()
        self.responses.close()


class AsyncPool(object):
    def __init__(self, callback, usrp):
        self.callback = callback
        self.usrp = usrp
        self.msgs = []
        self.closed = False

    def send(self, msg):
        self.msgs.append(msg)

    def get(self, block=True, timeout=None): # unused pylint: disable=W0613
        return self.callback(self.usrp, self.msgs.pop(0))

    def close(self):
        self.closed = True

    def join(self):
        pass


def _loop(_worker_num, callback, usrp, requests, responses):
    try:
        keep_going = True
        while keep_going:
            keep_going, args = requests.get(block=True)
            if keep_going:
                resp = callback(usrp, args)
                responses.put(resp)
    except Queue.Empty:
        pass
    except IOError:
        pass