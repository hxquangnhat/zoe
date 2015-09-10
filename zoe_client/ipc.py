import logging

import zmq

log = logging.getLogger(__name__)


class ZoeIPCClient:
    def __init__(self, server, port=8723):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect("tcp://%s:%d" % (server, port))
        log.debug("ZMQ socket connected")

    def _ask(self, message: dict) -> dict:
        self.socket.send_json(message)
        answer = self.socket.recv_json()
        if self._is_error(answer):
            log.info("IPC error: {}".format(self._error(answer)))
            return None
        else:
            return self._answer(answer)

    def ask(self, command: str, **kwargs) -> dict:
        q = {
            'command': command,
            'args': kwargs
        }
        return self._ask(q)

    def _is_error(self, message: dict) -> bool:
        return message['status'] == 'error'

    def _error(self, message: dict) -> str:
        return message['answer']

    def _answer(self, message: dict) -> dict:
        return message['answer']
