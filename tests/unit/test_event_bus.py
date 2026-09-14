import unittest

from core.event_bus import DomainEvent, EventBus


class EventBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_is_idempotent(self):
        bus = EventBus()
        calls = []

        async def handler(event):
            calls.append(event.event_id)

        bus.subscribe(DomainEvent.CASE_CREATED, handler)
        bus.subscribe(DomainEvent.CASE_CREATED, handler)
        event = DomainEvent(
            event_type=DomainEvent.CASE_CREATED,
            tenant_id="00000000-0000-0000-0000-000000000401",
            aggregate_type="case",
            aggregate_id="00000000-0000-0000-0000-000000000402",
            payload={},
        )

        errors = await bus._dispatch(event)

        self.assertEqual(errors, [])
        self.assertEqual(calls, [event.event_id])

    async def test_handler_failure_is_reported_for_persistence(self):
        bus = EventBus()

        async def broken_handler(event):
            raise TimeoutError("provider detail")

        bus.subscribe(DomainEvent.CASE_CREATED, broken_handler)
        event = DomainEvent(
            event_type=DomainEvent.CASE_CREATED,
            tenant_id="00000000-0000-0000-0000-000000000401",
            aggregate_type="case",
            aggregate_id="00000000-0000-0000-0000-000000000402",
            payload={},
        )

        errors = await bus._dispatch(event)

        self.assertEqual(errors, ["broken_handler:TimeoutError"])
        self.assertNotIn("provider detail", errors[0])


if __name__ == "__main__":
    unittest.main()
