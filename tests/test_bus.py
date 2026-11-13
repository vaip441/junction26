from terminal.bus import Bus


def test_publish_reaches_every_subscriber():
    bus = Bus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("tick", {"id": 1})
    assert a.get_nowait() == ("tick", {"id": 1}) and b.get_nowait() == ("tick", {"id": 1})


def test_publish_drops_a_full_subscriber_without_raising():
    bus = Bus()
    stalled = bus.subscribe()
    for i in range(1001):
        bus.publish("tick", {"id": i})
    fresh = bus.subscribe()
    bus.publish("tick", {"id": "after"})
    assert fresh.get_nowait() == ("tick", {"id": "after"})
    assert stalled.qsize() == 1000  # dropped: it never received the later events


def test_unsubscribe_stops_delivery():
    bus = Bus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # twice is harmless
    bus.publish("tick", {})
    assert q.empty()
