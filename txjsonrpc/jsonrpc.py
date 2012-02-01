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

    _failAllReason = None
    transport = None

    def __init__(self):
        self._counter = itertools.count(1)
        self._requests = {}

    def connectionMade(self):
        self.transport.protocol = self
        host, peer = self.transport.getHost(), self.transport.getPeer()
        log.msg("JSON RPC connection established (HOST: {}, PEER: {})".format(
            host, peer
        ))

    def connectionLost(self, reason):
        host, peer = self.transport.getHost(), self.transport.getPeer()
        log.msg(
            "JSON RPC connection lost (HOST: {}, PEER: {})".format(host, peer)
        )

        self.transport = None
        self.failAll(reason)


    def stringReceived(self, string):
        try:
            received = jsonrpclib.loads(string)
        except jsonrpclib.ParseError:
            return self.unhandledError(failure.Failure())

        if "result" in received or "error" in received:
            return self._receivedResult(received)
        else:
            return self._receivedRequest(received)

    def _receivedResult(self, result):
        id = result.get("id")

        try:
            d = self._requests.pop(id).addErrback(self.unhandledError, id=id)
        except KeyError:
            return self.unhandledError(failure.Failure())

        try:
            res = jsonrpclib.receivedResult(result)
        except KeyboardInterrupt:
            raise
        except:
            d.errback(failure.Failure())
        else:
            d.callback(res["result"])

    def _receivedRequest(self, request):
        try:
            req = jsonrpclib.receivedRequest(request, self.lookupMethod)
        except KeyboardInterrupt:
            raise
        except:
            return self.unhandledError(failure.Failure())

        id = request.get("id")
        d = defer.maybeDeferred(req["method"], *req["args"], **req["kwargs"])

        if id is not None:
            d.addCallback(lambda res : jsonrpclib.response(id, res))

        # we want invalid notifications to cause errors too, so no addCallbacks
        d.addErrback(self.unhandledError, id=id)

        if id is not None:
            d.addCallback(self.sendString)

    def sendString(self, string):
        if self.transport is None:
            raise error.ConnectionLost()
        basic.Int16StringReceiver.sendString(self, string)

    def failAll(self, reason):
        self._failAllReason = reason
        requests, self._requests = self._requests, None

        for request in requests.itervalues():
            request.errback(reason)

    def unhandledError(self, failure, id=None):
        log.err(
            failure,
            "An error went unhandled by the client application. "
            "Dropping connection. To avoid this, add errbacks to all remote "
            "requests and verify that valid JSON is being sent."
        )

        if self.transport is not None:
            self.sendString(jsonrpclib.error(id, failure))
            self.transport.loseConnection()

    def _buildOutgoing(self, method, parameters, notification=False):
        if self._failAllReason is not None:
            return defer.fail(self._failAllReason)

        if notification:
            toSend = jsonrpclib.notify(method, parameters)
        else:
            id = str(next(self._counter))
            toSend = jsonrpclib.request(id, method, parameters)

        self.sendString(toSend)

        if not notification:
            return self._requests.setdefault(id, defer.Deferred())

    def notify(self, method, parameters=()):
        return self._buildOutgoing(
            method=method, parameters=parameters, notification=True,
        )

    def request(self, method, parameters=()):
        return self._buildOutgoing(
            method=method, parameters=parameters, notification=False,
        )


class JSONRPCFactory(protocol.Factory):
    protocol = JSONRPC

    def __init__(self, lookupMethod=lambda name : None):
        self.lookupMethod = lookupMethod

    def buildProtocol(self, addr):
        proto = protocol.Factory.buildProtocol(self, addr)
        proto.lookupMethod = self.lookupMethod
        return proto
