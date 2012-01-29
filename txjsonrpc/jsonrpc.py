"""
This module, along with :module:`jsonrpclib`, naively implement JSON RPC.

All of the implementations I found were either resource-based or really ugly.

"""

import itertools

from twisted.internet import defer, error, protocol
from twisted.protocols import basic
from twisted.python import failure, log

from txjsonrpc import jsonrpclib


class JSONRPC(basic.Int16StringReceiver):

    _fail_all_reason = None
    transport = None

    def __init__(self):
        self._counter = itertools.count(1)
        self._requests = {}

    def connectionMade(self):
        self.transport.protocol = self
        host, peer = self.transport.getHost(), self.transport.getPeer()
        log.msg("{} connection established (HOST: {}, PEER: {})".format(
            self.__class__.__name__, host, peer
        ))

    def connectionLost(self, reason):
        host, peer = self.transport.getHost(), self.transport.getPeer()
        log.msg("{} connection lost (HOST: {}, PEER: {})".format(
            self.__class__.__name__, host, peer
        ))

        self.transport = None
        self.fail_all(reason)


    def stringReceived(self, string):
        try:
            received = jsonrpclib.loads(string)
        except jsonrpclib.ParseError:
            return self.unhandled_error(failure.Failure())

        if "result" in received or "error" in received:
            return self._received_result(received)
        else:
            return self._received_request(received)

    def _received_result(self, result):
        id = result.get("id")

        try:
            d = self._requests.pop(id).addErrback(self.unhandled_error, id=id)
        except KeyError:
            return self.unhandled_error(failure.Failure())

        try:
            res = jsonrpclib.received_result(result)
        except KeyboardInterrupt:
            raise
        except:
            d.errback(failure.Failure())
        else:
            d.callback(res["result"])

    def _received_request(self, request):
        try:
            req = jsonrpclib.received_request(request, self.lookup_method)
        except KeyboardInterrupt:
            raise
        except:
            return self.unhandled_error(failure.Failure())

        id = request.get("id")
        d = defer.maybeDeferred(req["method"], *req["args"], **req["kwargs"])

        if id is not None:
            d.addCallback(lambda res : jsonrpclib.response(id, res))

        # we want invalid notifications to cause errors too, so no addCallbacks
        d.addErrback(self.unhandled_error, id=id)

        if id is not None:
            d.addCallback(self.sendString)

    def sendString(self, string):
        if self.transport is None:
            raise error.ConnectionLost()
        basic.Int16StringReceiver.sendString(self, string)

    def fail_all(self, reason):
        self._fail_all_reason = reason
        requests, self._requests = self._requests, None

        for request in requests.itervalues():
            request.errback(reason)

    def unhandled_error(self, failure, id=None):
        log.err(
            failure,
            "An error went unhandled by the client application. "
            "Dropping connection. To avoid this, add errbacks to all remote "
            "requests and verify that valid JSON is being sent."
        )

        if self.transport is not None:
            self.sendString(jsonrpclib.error(id, failure))
            self.transport.loseConnection()

    def _build_outgoing(self, method, parameters, notification=False):
        if self._fail_all_reason is not None:
            return defer.fail(self._fail_all_reason)

        if notification:
            to_send = jsonrpclib.notify(method, parameters)
        else:
            id = str(next(self._counter))
            to_send = jsonrpclib.request(id, method, parameters)

        self.sendString(to_send)

        if not notification:
            return self._requests.setdefault(id, defer.Deferred())

    def notify(self, method, parameters=()):
        return self._build_outgoing(
            method=method, parameters=parameters, notification=True,
        )

    def request(self, method, parameters=()):
        return self._build_outgoing(
            method=method, parameters=parameters, notification=False,
        )


class JSONRPCFactory(protocol.Factory):
    protocol = JSONRPC

    def __init__(self, lookup_method=lambda name : None):
        self.lookup_method = lookup_method

    def buildProtocol(self, addr):
        proto = protocol.Factory.buildProtocol(self, addr)
        proto.lookup_method = self.lookup_method
        return proto
