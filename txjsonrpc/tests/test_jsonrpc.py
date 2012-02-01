from __future__ import absolute_import
import json

from twisted.internet import defer, error
from twisted.python import failure
from twisted.test import proto_helpers
from twisted.trial import unittest

from txjsonrpc import jsonrpc, jsonrpclib


class TestJSONRPC(unittest.TestCase):
    def setUp(self):
        self.deferred = defer.Deferred()

        exposed = {
            "foo" : lambda : setattr(self, "fooFired", True),
            "bar" : lambda p : setattr(self, "barResult", p ** 2),
            "baz" : lambda p, q : (q, p),
            "late" : lambda p : self.deferred,
        }

        self.factory = jsonrpc.JSONRPCFactory(exposed.get)
        self.proto = self.factory.buildProtocol(("127.0.0.1", 0))
        self.tr = proto_helpers.StringTransportWithDisconnection()
        self.proto.makeConnection(self.tr)

    def assertSent(self, expected):
        expected["jsonrpc"] = "2.0"
        self.assertEqual(json.loads(self.tr.value()[2:]), expected)

    def test_notify(self):
        """
        notify() sends a valid JSON RPC notification.

        """

        self.proto.notify("foo")
        self.assertSent({"method" : "foo", "params" : []})

        self.tr.clear()

        self.proto.notify("bar", [3])
        self.assertSent({"method" : "bar", u"params" : [3]})

    def test_request(self):
        """
        request() sends a valid JSON RPC request and returns a deferred.

        """

        d = self.proto.request("foo")
        self.assertSent({"id" : "1", "method" : "foo", "params" : []})

        d.addCallback(lambda r : self.assertEqual(r, [2, 3, "bar"]))

        receive = {"jsonrpc" : "2.0", "id" :  "1", "result" : [2, 3, "bar"]}
        self.proto.stringReceived(json.dumps(receive))
        return d

    def test_unhandledError(self):
        """
        An unhandled error gets logged and disconnects the transport.

        """

        v = failure.Failure(ValueError("Hey a value error"))
        self.proto.unhandledError(v)

        errors = self.flushLoggedErrors(ValueError)
        self.assertEqual(errors, [v])

    def test_invalid_json(self):
        """
        Invalid JSON causes a JSON RPC ParseError and disconnects.

        """

        self.proto.stringReceived("[1,2,")

        err = {"id" : None, "error" : jsonrpclib.ParseError().toResponse()}
        self.assertSent(err)

        errors = self.flushLoggedErrors(jsonrpclib.ParseError)
        self.assertEqual(len(errors), 1)

    def test_invalid_request(self):
        """
        An invalid request causes a JSON RPC InvalidRequest and disconnects.

        """

        self.proto.stringReceived(json.dumps({"id" : 12}))

        err = jsonrpclib.InvalidRequest({"reason" : "jsonrpc"})
        self.assertSent({"id" : None, "error" : err.toResponse()})

        errors = self.flushLoggedErrors(jsonrpclib.InvalidRequest)
        self.assertEqual(len(errors), 1)

    def test_unsolicited_result(self):
        """
        An incoming result for an id that does not exist raises an error.

        """

        receive = {"jsonrpc" : "2.0", "id" :  "1", "result" : [2, 3, "bar"]}
        self.proto.stringReceived(json.dumps(receive))

        err = jsonrpclib.InternalError({
            "exception" : "KeyError", "message" : "u'1'",
        })
        expect = {"jsonrpc" : "2.0", "id" : None, "error" : err.toResponse()}
        sent = json.loads(self.tr.value()[2:])
        tb = sent["error"]["data"].pop("traceback")

        self.assertEqual(sent, expect)
        self.assertTrue(tb)

        # TODO: Raises original exception. Do we want InternalError instead?
        errors = self.flushLoggedErrors(KeyError)
        self.assertEqual(len(errors), 1)

    def _errorTest(self, err):
        d = self.proto.request("foo").addErrback(lambda f : self.assertEqual(
            f.value.toResponse(), err.toResponse()
        ))

        receive = {"jsonrpc" : "2.0", "id" : "1", "error" : {}}
        receive["error"] = {"code" : err.code, "message" : err.message}
        self.proto.stringReceived(json.dumps(receive))
        return d

    def test_parse_error(self):
        self._errorTest(jsonrpclib.ParseError())

    def test_invalid_request(self):
        self._errorTest(jsonrpclib.InvalidRequest())

    def test_method_not_found(self):
        self._errorTest(jsonrpclib.MethodNotFound())

    def test_invalid_params(self):
        self._errorTest(jsonrpclib.InvalidParams())

    def test_internal_error(self):
        self._errorTest(jsonrpclib.InternalError())

    def test_application_error(self):
        self._errorTest(jsonrpclib.ApplicationError(code=2400, message="Go."))

    def test_server_error(self):
        self._errorTest(jsonrpclib.ServerError(code=-32020))

    def test_received_notify(self):
        receive = {"jsonrpc" : "2.0", "method" : "foo"}
        self.proto.stringReceived(json.dumps(receive))
        self.assertTrue(self.fooFired)

        receive = {"jsonrpc" : "2.0", "method" : "bar", "params" : [2]}
        self.proto.stringReceived(json.dumps(receive))
        self.assertEqual(self.barResult, 4)

    def test_received_notify_no_method(self):
        receive = {"jsonrpc" : "2.0", "method" : "quux"}
        self.proto.stringReceived(json.dumps(receive))
        errors = self.flushLoggedErrors(jsonrpclib.MethodNotFound)
        self.assertEqual(len(errors), 1)

    def test_received_notify_wrong_param_type(self):
        receive = {"jsonrpc" : "2.0", "method" : "foo", "params" : [1, 2]}
        self.proto.stringReceived(json.dumps(receive))

        receive = {"jsonrpc" : "2.0", "method" : "bar", "params" : "foo"}
        self.proto.stringReceived(json.dumps(receive))

        errors = self.flushLoggedErrors(TypeError)
        self.assertEqual(len(errors), 2)

    def test_received_request(self):
        receive = {
            "jsonrpc" : "2.0", "id" : "1", "method" : "baz", "params" : [1, 2]
        }

        self.proto.stringReceived(json.dumps(receive))
        self.assertSent({"jsonrpc" : "2.0", "id" : "1", "result" : [2, 1]})

    def test_received_request_deferred(self):
        receive = {
            "jsonrpc" : "2.0", "id" : "3",
            "method" : "late", "params" : {"p" : 3}
        }

        self.proto.stringReceived(json.dumps(receive))
        self.deferred.callback(27)
        self.assertSent({"jsonrpc" : "2.0", "id" : "3", "result" : 27})

    def test_received_request_no_method(self):
        receive = {"jsonrpc" : "2.0", "id" : "3", "method" : "quux"}
        self.proto.stringReceived(json.dumps(receive))
        errors = self.flushLoggedErrors(jsonrpclib.MethodNotFound)
        self.assertEqual(len(errors), 1)

        sent = json.loads(self.tr.value()[2:])
        self.assertIn("error", sent)
        self.assertEqual(sent["error"]["code"], jsonrpclib.MethodNotFound.code)

    def test_received_request_error(self):
        receive = {
            "jsonrpc" : "2.0", "id" : "1", "method" : "foo", "params" : [1, 2]
        }
        self.proto.stringReceived(json.dumps(receive))

        response = json.loads(self.tr.value()[2:])

        self.assertNotIn("result", response)
        self.assertEqual(response["id"], "1")
        self.assertEqual(response["error"]["data"]["exception"], "TypeError")
        self.assertTrue(response["error"]["data"]["traceback"])

        errors = self.flushLoggedErrors(TypeError)
        self.assertEqual(len(errors), 1)

        errors = self.flushLoggedErrors(error.ConnectionLost)
        self.assertEqual(len(errors), 1)

    def test_fail_all(self):
        d1, d2 = self.proto.request("foo"), self.proto.request("bar", [1, 2])
        exc = failure.Failure(ValueError("A ValueError"))
        self.proto.failAll(exc)

        d3 = self.proto.request("baz", "foo")

        for d in d1, d2, d3:
            d.addErrback(lambda reason: self.assertIs(reason, exc))

    def test_connection_lost(self):
        self.proto.connectionLost(failure.Failure(error.ConnectionLost("Bye")))
        return self.proto.request("foo").addErrback(
            lambda f : self.assertIs(f.type, error.ConnectionLost)
        )
