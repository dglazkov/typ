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

import copy
import multiprocessing
import pickle

try:
    from enum import Enum
except ImportError: # pragma: no cover
    Enum = object

from typ.host import Host



class _MessageType(Enum):
    # Class has no __init__ pylint: disable=W0232
    Request = 1
    Response = 2
    Close = 3
    Done = 4
    Error = 5


def make_pool(host, jobs, callback, context, pre_fn, post_fn):
    # TODO: Fix the fake test loader in main_test so that we can assert this.
    #try:
    #    _ = pickle.dumps(context)
    #except Exception as e:
    #    raise ValueError('context passed to make_pool is not picklable: %s'
    #                     % str(e))
    try:
        _ = pickle.dumps(pre_fn)
    except pickle.PickleError: # pragma: no cover
        raise ValueError('pre_fn passed to make_pool is not picklable')
    try:
        _ = pickle.dumps(post_fn)
    except pickle.PickleError: # pragma: no cover
        raise ValueError('post_fn passed to make_pool is not picklable')
    cls = ProcessPool if jobs > 1 else AsyncPool
    return cls(host, jobs, callback, context, pre_fn, post_fn)


class ProcessPool(object):
    def __init__(self, host, jobs, callback, context, pre_fn, post_fn):
        self.host = host
        self.jobs = jobs
        self.requests = multiprocessing.Queue()
        self.responses = multiprocessing.Queue()
        self.workers = []
        self.closed = False
        self.erred = False
        for worker_num in range(jobs):
            w = multiprocessing.Process(target=_loop,
                                        args=(self.requests, self.responses,
                                              host.for_mp(), worker_num,
                                              callback, context,
                                              pre_fn, post_fn))
            w.start()
            self.workers.append(w)

    def send(self, msg):
        self.requests.put((_MessageType.Request, msg))

    def get(self, block=True, timeout=None):
        msg_type, resp = self.responses.get(block, timeout)
        if msg_type == _MessageType.Error: # pragma: no cover
            self._handle_error(resp)
        assert msg_type == _MessageType.Response
        return resp

    def close(self):
        for _ in self.workers:
            self.requests.put((_MessageType.Close, None))
        self.requests.close()
        self.closed = True

    def join(self):
        final_responses = []
        if not self.closed:
            self.requests.close()
            for w in self.workers:
                w.terminate()
                w.join()
        else:
            for w in self.workers:
                while True:
                    msg_type, resp = self.responses.get(True)
                    if msg_type == _MessageType.Error: # pragma: no cover
                        self._handle_error(resp)
                    elif msg_type == _MessageType.Done:
                        break
                    # TODO: log something about discarding messages?
                final_responses.append(resp)
                w.join()
        self.responses.close()
        return final_responses

    def _handle_error(self, msg): # pragma: no cover
        worker_num, ex_str = msg
        self.erred = True
        raise Exception("error from worker %d: %s" % (worker_num, ex_str))


class AsyncPool(object):
    def __init__(self, host, jobs, callback, context, pre_fn, post_fn):
        self.host = host or Host()
        self.jobs = jobs
        self.callback = callback
        self.context = copy.deepcopy(context)
        self.msgs = []
        self.closed = False
        self.post_fn = post_fn
        self.context_after_pre = pre_fn(self.host, 1, self.context)
        self.final_context = None

    def send(self, msg):
        self.msgs.append(msg)

    def get(self, block=True, timeout=None):
        # unused pylint: disable=W0613
        return self.callback(self.context_after_pre, self.msgs.pop(0))

    def close(self):
        self.closed = True
        self.final_context = self.post_fn(self.context_after_pre)

    def join(self):
        if not self.closed:
            self.close()
        return [self.final_context]


def _loop(requests, responses, host, worker_num,
          callback, context, pre_fn, post_fn): # pragma: no cover
    # TODO: Figure out how to get coverage to work w/ subprocesses.
    host = host or Host()
    erred = False
    try:
        context_after_pre = pre_fn(host, worker_num, context)
        while True:
            message_type, args = requests.get(block=True)
            if message_type == _MessageType.Close:
                break
            assert message_type == _MessageType.Request
            resp = callback(context_after_pre, args)
            responses.put((_MessageType.Response, resp))
    except Exception as e:
        erred = True
        responses.put((_MessageType.Error, (worker_num, str(e))))

    try:
        if not erred:
            responses.put((_MessageType.Done, post_fn(context_after_pre)))
    except Exception:
        pass
