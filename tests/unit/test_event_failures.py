import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from core.event_bus import DomainEvent, EventBus
from automation.scheduler import run_periodically
from automation.task_queue import TaskQueue, auto_escalate_async, send_notification_async
from database.repositories import CaseRepository


TENANT_ID="00000000-0000-0000-0000-000000000001"
AGGREGATE_ID="00000000-0000-0000-0000-000000000002"


def event(**changes):
    return DomainEvent(**{"event_type":DomainEvent.CASE_CREATED,"tenant_id":TENANT_ID,"aggregate_type":"case","aggregate_id":AGGREGATE_ID,"payload":{},**changes})


class Session:
    def __init__(self, record=None, fail_commit=False):
        self.record=record
        self.fail_commit=fail_commit
        self.queries=[]
        self.commits=0
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def execute(self,query):
        self.queries.append(query)
        return SimpleNamespace(scalar_one_or_none=lambda:self.record)
    async def commit(self):
        self.commits+=1
        if self.fail_commit:raise OSError("synthetic DB failure")


class InlineSession(Session):
    def __init__(self):
        super().__init__()
        self.added=[]
        self.flushes=0
    def add(self,record):
        if any(existing.id == record.id for existing in self.added):
            raise RuntimeError("duplicate event id")
        self.added.append(record)
        self.record=record
    async def flush(self):
        self.flushes+=1


class EventFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_inline_delivery_persists_then_marks_processed(self):
        bus=EventBus()
        received=[]
        async def handler(value):received.append(value.event_id)
        item=event()
        bus.subscribe(item.event_type,handler)
        db=InlineSession()
        self.assertEqual(await bus.publish(item,db=db),item.event_id)
        self.assertEqual(received,[item.event_id])
        self.assertEqual(db.flushes,1)
        self.assertTrue(db.record.processed)
        self.assertIsNone(db.record.error)
        self.assertIsNotNone(db.record.processed_at.tzinfo)

    async def test_duplicate_event_id_fails_before_second_delivery(self):
        bus=EventBus()
        received=[]
        async def handler(value):received.append(value.event_id)
        item=event()
        bus.subscribe(item.event_type,handler)
        db=InlineSession()
        await bus.publish(item,db=db)
        with self.assertRaises(RuntimeError):await bus.publish(item,db=db)
        self.assertEqual(received,[item.event_id])

    def test_malformed_and_unknown_events_fail_at_boundary(self):
        naive=__import__("datetime").datetime.utcnow()
        for changes in ({"event_type":"UNKNOWN"},{"tenant_id":""},{"tenant_id":"not-a-uuid"},{"aggregate_type":"shell"},{"aggregate_id":""},{"aggregate_id":"not-a-uuid"},{"payload":[]},{"payload":{"score":float("nan")}},{"payload":{"object":object()}},{"occurred_at":naive}):
            with self.subTest(changes=list(changes)),self.assertRaises(ValueError):event(**changes)

    async def test_payload_snapshot_and_partial_failure_isolation(self):
        source={"nested":{"value":"original"}}
        item=event(payload=source)
        source["nested"]["value"]="caller modification"
        bus=EventBus()
        received=[]
        async def broken(value):
            value.payload["nested"]["value"]="handler modification"
            raise ValueError("private provider detail")
        async def healthy(value):received.append(value.payload["nested"]["value"])
        bus.subscribe(item.event_type,broken)
        bus.subscribe(item.event_type,healthy)
        with self.assertLogs("core.event_bus",level="ERROR") as logs:
            self.assertEqual(await bus._dispatch(item),["broken:ValueError"])
        self.assertEqual(received,["original"])
        self.assertIn(item.event_id,logs.output[0])
        self.assertNotIn("private provider detail",logs.output[0])

    async def test_persistence_failure_never_dispatches_or_schedules(self):
        bus=EventBus()
        background=SimpleNamespace(add_task=AsyncMock())
        with patch.object(bus,"_persist",new_callable=AsyncMock,side_effect=OSError),patch.object(bus,"_dispatch",new_callable=AsyncMock) as dispatch:
            with self.assertRaises(OSError):await bus.publish(event(),db=object(),background_tasks=background)
            background.add_task.assert_not_called()
            dispatch.assert_not_awaited()

    async def test_deferred_delivery_is_scheduled_only_after_persistence(self):
        order=[]
        bus=EventBus()
        async def persist(*args):order.append("persisted")
        class Background:
            def add_task(self,fn,item):
                self.fn=fn
                self.item=item
                order.append("scheduled")
        background=Background()
        with patch.object(bus,"_persist",side_effect=persist):
            item=event()
            self.assertEqual(await bus.publish(item,db=object(),background_tasks=background),item.event_id)
        self.assertEqual(order,["persisted","scheduled"])
        self.assertEqual(background.fn,bus._dispatch_and_mark)
        self.assertEqual(background.item.event_id,item.event_id)

    async def test_duplicate_deferred_dispatch_is_claimed_once(self):
        bus=EventBus()
        item=event()
        record=SimpleNamespace(processed=False,error=None)
        db=Session(record)
        with patch("database.base.AsyncSessionLocal",return_value=db),patch.object(bus,"_dispatch",new_callable=AsyncMock,return_value=[]) as dispatch:
            await bus._dispatch_and_mark(item)
            await bus._dispatch_and_mark(item)
            dispatch.assert_awaited_once()
        self.assertTrue(record.processed)
        self.assertIsNone(record.error)
        self.assertIn("FOR UPDATE",str(db.queries[0]))
        self.assertIn("tenant_id",str(db.queries[0]))

    async def test_claim_failure_or_missing_event_prevents_dispatch(self):
        for db in (Session(),Session(SimpleNamespace(processed=False,error=None),True)):
            bus=EventBus()
            with patch("database.base.AsyncSessionLocal",return_value=db),patch.object(bus,"_dispatch",new_callable=AsyncMock) as dispatch:
                with self.assertRaises((RuntimeError,OSError)):await bus._dispatch_and_mark(event())
                dispatch.assert_not_awaited()

    async def test_handler_failure_is_recorded_without_automatic_retry(self):
        record=SimpleNamespace(processed=False,error=None)
        db=Session(record)
        bus=EventBus()
        item=event()
        with patch("database.base.AsyncSessionLocal",return_value=db),patch.object(bus,"_dispatch",new_callable=AsyncMock,return_value=["handler:TimeoutError"]) as dispatch:
            await bus._dispatch_and_mark(item)
            await bus._dispatch_and_mark(item)
            dispatch.assert_awaited_once()
        self.assertEqual(record.error,"handler:TimeoutError")

    async def test_completion_mark_failure_leaves_claim_diagnosable(self):
        record=SimpleNamespace(processed=False,error=None,processed_at=None)
        db=Session(record)
        commits=[]
        async def commit():
            commits.append(record.error)
            if len(commits)==2:raise OSError("synthetic completion failure")
        db.commit=commit
        bus=EventBus()
        with patch("database.base.AsyncSessionLocal",return_value=db),patch.object(bus,"_dispatch",new_callable=AsyncMock,return_value=[]):
            with self.assertRaises(OSError):await bus._dispatch_and_mark(event())
        self.assertTrue(record.processed)
        self.assertEqual(commits,["dispatch_in_progress",None])
        self.assertIsNotNone(record.processed_at.tzinfo)

    async def test_replay_is_tenant_scoped_and_exposes_processing_diagnostics(self):
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        row=SimpleNamespace(id="event-id",event_type=DomainEvent.CASE_CREATED,aggregate_type="case",aggregate_id="case-id",payload={},processed=True,processed_at=now,error="handler:TimeoutError",created_at=now)
        db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[row]))))
        result=await EventBus().replay(tenant_id=TENANT_ID,db=db)
        self.assertEqual(result[0]["error"],"handler:TimeoutError")
        self.assertEqual(result[0]["processed_at"],now.isoformat())
        self.assertIn("tenant_id",str(db.execute.call_args.args[0]))

    async def test_task_failure_and_unknown_task_are_not_retried(self):
        queue=TaskQueue()
        calls=[]
        @queue.register("broken")
        async def broken():
            calls.append(1)
            raise TimeoutError("synthetic")
        with self.assertRaises(KeyError):await queue.run("unknown")
        with self.assertRaises(TimeoutError):await queue.run("broken")
        self.assertEqual(calls,[1])

    async def test_escalation_lock_is_tenant_scoped(self):
        result=SimpleNamespace(scalar_one_or_none=lambda:None)
        db=SimpleNamespace(execute=AsyncMock(return_value=result))
        await CaseRepository(db,TENANT_ID).get_for_update(AGGREGATE_ID)
        query=str(db.execute.call_args.args[0])
        self.assertIn("FOR UPDATE",query)
        self.assertIn("cases.tenant_id",query)
        self.assertIn("cases.id",query)

    async def test_duplicate_escalation_attempt_creates_one_event(self):
        case=SimpleNamespace(status="IN_REVIEW")
        class Repo:
            def __init__(self,*args):pass
            async def get_for_update(self,case_id):return case
            async def update_status(self,*,case_id,status):case.status=status
        db=Session()
        bus=SimpleNamespace(publish=AsyncMock())
        audit=SimpleNamespace(log_state_transition=Mock())
        with patch("database.base.AsyncSessionLocal",return_value=db),patch("database.repositories.CaseRepository",Repo),patch("core.event_bus.get_event_bus",return_value=bus),patch("core.audit_logger.get_audit_logger",return_value=audit):
            args=dict(tenant_id=TENANT_ID,case_id=AGGREGATE_ID,escalation_target="legal",reason="synthetic",risk_score=90)
            await auto_escalate_async(**args)
            await auto_escalate_async(**args)
        self.assertEqual(case.status,"ESCALATED")
        bus.publish.assert_awaited_once()
        audit.log_state_transition.assert_called_once()

    async def test_notification_cannot_emit_external_intent(self):
        with self.assertRaises(NotImplementedError):
            await send_notification_async(tenant_id=TENANT_ID,case_id=AGGREGATE_ID,notification_type="email",recipient="synthetic@example.com",payload={})

    async def test_scheduler_survives_failure_then_propagates_cancellation(self):
        fn=AsyncMock(side_effect=[TimeoutError("private detail"),None])
        with patch("automation.scheduler.asyncio.sleep",new_callable=AsyncMock,side_effect=[None,None,asyncio.CancelledError()]):
            with self.assertRaises(asyncio.CancelledError):await run_periodically(fn,1,"synthetic")
        self.assertEqual(fn.await_count,2)
