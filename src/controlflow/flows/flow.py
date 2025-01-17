import uuid
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from pydantic import Field

import controlflow
from controlflow.agents import Agent
from controlflow.events.base import Event
from controlflow.events.history import History
from controlflow.flows.graph import Graph
from controlflow.tasks.task import Task
from controlflow.utilities.context import ctx
from controlflow.utilities.logging import get_logger
from controlflow.utilities.prefect import prefect_flow_context
from controlflow.utilities.types import ControlFlowModel

if TYPE_CHECKING:
    from controlflow.orchestration.agent_context import AgentContext

logger = get_logger(__name__)


class Flow(ControlFlowModel):
    model_config = dict(arbitrary_types_allowed=True)
    thread_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: Optional[str] = None
    description: Optional[str] = None
    history: History = Field(default_factory=lambda: controlflow.defaults.history)
    tools: list[Callable] = Field(
        default_factory=list,
        description="Tools that will be available to every agent in the flow",
    )
    agent: Optional[Agent] = Field(
        None,
        description="The default agent for the flow. This agent will be used "
        "for any task that does not specify an agent.",
    )
    prompt: Optional[str] = Field(
        None,
        description="A prompt to display to the agent working on the flow. "
        "Prompts are formatted as jinja templates, with keywords `flow: Flow` and `context: AgentContext`.",
    )
    context: dict[str, Any] = {}
    graph: Graph = Field(default_factory=Graph, repr=False, exclude=True)
    _cm_stack: list[contextmanager] = []

    def __init__(self, *, copy_parent: bool = True, **kwargs):
        """
        By default, the flow will copy the event history from the parent flow if one
        exists, including all completed tasks. Because each flow is a new
        thread, new events will not be shared between the parent and child
        flow.
        """
        super().__init__(**kwargs)
        parent = get_flow()
        if parent and copy_parent:
            self.add_events(parent.get_events())
            for task in parent.tasks:
                if task.is_complete():
                    self.add_task(task)

    def __enter__(self):
        # use stack so we can enter the context multiple times
        cm = self.create_context()
        self._cm_stack.append(cm)
        return cm.__enter__()

    def __exit__(self, *exc_info):
        # exit the context manager
        return self._cm_stack.pop().__exit__(*exc_info)

    def add_task(self, task: Task):
        self.graph.add_task(task)

    @property
    def tasks(self) -> list[Task]:
        return self.graph.topological_sort()

    def get_prompt(self, context: "AgentContext") -> str:
        """
        Generate a prompt to share information about the flow with an agent.
        """
        from controlflow.orchestration import prompt_templates

        template = prompt_templates.FlowTemplate(
            template=self.prompt,
            flow=self,
            context=context,
        )
        return template.render()

    def get_events(
        self,
        agents: Optional[list[Agent]] = None,
        tasks: Optional[list[Task]] = None,
        before_id: Optional[str] = None,
        after_id: Optional[str] = None,
        limit: Optional[int] = None,
        types: Optional[list[str]] = None,
    ) -> list[Event]:
        return self.history.get_events(
            thread_id=self.thread_id,
            agent_ids=[agent.id for agent in agents or []],
            task_ids=[task.id for task in tasks or []],
            before_id=before_id,
            after_id=after_id,
            limit=limit,
            types=types,
        )

    def add_events(self, events: list[Event]):
        self.history.add_events(thread_id=self.thread_id, events=events)

    @contextmanager
    def create_context(self, create_prefect_flow_context: bool = True):
        ctx_args = dict(flow=self)
        if create_prefect_flow_context and ctx.get("prefect_flow") is not self:
            prefect_ctx = prefect_flow_context(name=self.name)
            ctx_args["prefect_flow"] = self
        else:
            prefect_ctx = nullcontext()

        with ctx(**ctx_args), prefect_ctx:
            yield self

    def run(self, steps: Optional[int] = None):
        """
        Runs the flow.
        """
        from controlflow.orchestration import Orchestrator

        orchestrator = Orchestrator(flow=self)
        orchestrator.run(steps=steps)

    async def run_async(self, steps: Optional[int] = None):
        """
        Runs the flow.
        """
        from controlflow.orchestration import Orchestrator

        orchestrator = Orchestrator(flow=self)
        await orchestrator.run_async(steps=steps)


def get_flow() -> Optional[Flow]:
    """
    Loads the flow from the context. If no flow is found, returns None.
    """
    flow: Union[Flow, None] = ctx.get("flow")
    return flow


def get_flow_events(limit: int = None) -> list[Event]:
    """
    Loads events from the active flow's thread.
    """
    if limit is None:
        limit = 50
    flow = get_flow()
    if flow:
        return flow.get_events(limit=limit)
    else:
        return []
