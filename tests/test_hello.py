from workflows.events import StepState, StepStateChanged
from workflows.testing import WorkflowTestRunner

from litreview.workflows.hello import Greet, Greeted, HelloWorkflow, Progress
from litreview.workflows.tiny_unbound import Shout, TinyWorkflow


async def test_loop_runs_once_per_round_and_streams_progress():
    r = await WorkflowTestRunner(HelloWorkflow(timeout=10)).run(Greet(name="Ada", rounds=3))

    assert isinstance(r.result, Greeted)  # custom StopEvent comes back as the instance itself
    assert r.result.message == "Hello Ada!"
    assert r.result.rounds_done == 3
    assert r.event_types[Progress] == 3
    tick_runs = [
        e
        for e in r.collected
        if isinstance(e, StepStateChanged) and e.name == "tick" and e.step_state == StepState.RUNNING
    ]
    assert len(tick_runs) == 3  # the loop: tick consumed its own output event twice more


async def test_empty_name_takes_the_short_branch():
    r = await WorkflowTestRunner(HelloWorkflow(timeout=10)).run(Greet(name="  "))

    assert r.result == Greeted(message="Nobody to greet.", rounds_done=0)
    assert Progress not in r.event_types  # tick never ran


async def test_unbound_function_workflow():
    r = await WorkflowTestRunner(TinyWorkflow(timeout=10)).run(Shout(text="hi"))

    assert r.result == "HI!"  # plain StopEvent: the runner returns .result


def test_events_round_trip_through_json():
    # Snapshots and durability rely on every event surviving JSON (spec rule 7).
    for ev in [Greet(name="Ada", rounds=2), Progress(message="x"), Greeted(message="m", rounds_done=1)]:
        assert type(ev).model_validate_json(ev.model_dump_json()) == ev
