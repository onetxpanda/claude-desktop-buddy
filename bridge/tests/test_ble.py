from __future__ import annotations

from claude_buddy_bridge.ble import FakeTransport


class TestFakeTransport:
    async def test_send_line_stores_in_sent(self):
        t = FakeTransport()
        await t.start()
        await t.send_line(b"hello\n")
        assert t.sent == [b"hello\n"]

    async def test_connect_fires_listener(self):
        t = FakeTransport()
        calls: list[bool] = []
        t.set_connection_listener(calls.append)
        t.simulate_connect()
        assert calls == [True]
        assert t.connected is True

    async def test_duplicate_connect_does_not_double_fire(self):
        t = FakeTransport()
        calls: list[bool] = []
        t.set_connection_listener(calls.append)
        t.simulate_connect()
        t.simulate_connect()
        assert calls == [True]

    async def test_disconnect_fires_listener(self):
        t = FakeTransport()
        calls: list[bool] = []
        t.set_connection_listener(calls.append)
        t.simulate_connect()
        t.simulate_disconnect()
        assert calls == [True, False]

    async def test_receive_passes_complete_lines(self):
        t = FakeTransport()
        received: list[bytes] = []
        t.set_line_listener(received.append)
        t.simulate_receive(b'{"ack":"owner","ok":true}\n')
        assert received == [b'{"ack":"owner","ok":true}']

    async def test_receive_buffers_partial_lines(self):
        t = FakeTransport()
        received: list[bytes] = []
        t.set_line_listener(received.append)
        t.simulate_receive(b'{"ack":')
        assert received == []
        t.simulate_receive(b'"owner","ok":true}\n')
        assert received == [b'{"ack":"owner","ok":true}']

    async def test_stop_while_connected_fires_disconnect(self):
        t = FakeTransport()
        calls: list[bool] = []
        t.set_connection_listener(calls.append)
        t.simulate_connect()
        await t.stop()
        assert calls == [True, False]
