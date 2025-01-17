from typing import Optional

from pydantic import model_validator

from controlflow.agents.agent import Agent
from controlflow.agents.teams import Team
from controlflow.flows import Flow
from controlflow.orchestration.agent_context import AgentContext
from controlflow.tasks.task import Task
from controlflow.utilities.jinja import prompt_env
from controlflow.utilities.types import ControlFlowModel


class Template(ControlFlowModel):
    model_config = dict(extra="allow")
    template: Optional[str] = None
    template_path: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self):
        if not self.template and not self.template_path:
            raise ValueError("Template or template_path must be provided.")
        return self

    def render(self, **kwargs) -> str:
        if not self.should_render():
            return ""

        render_kwargs = dict(self)
        del render_kwargs["template"]
        del render_kwargs["template_path"]

        if self.template is not None:
            template = prompt_env.from_string(self.template)
        else:
            template = prompt_env.get_template(self.template_path)
        return template.render(**render_kwargs | kwargs)

    def should_render(self) -> bool:
        return True


class AgentTemplate(Template):
    template_path: str = "agent.md.jinja"
    agent: Agent
    context: AgentContext


class TaskTemplate(Template):
    """
    Template for the active tasks
    """

    template_path: str = "task.md.jinja"
    task: Task
    context: AgentContext


class FlowTemplate(Template):
    template_path: str = "flow.md.jinja"
    flow: Flow
    context: AgentContext

    def render(self, **kwargs):
        upstream_tasks = set(self.flow.graph.upstream_tasks(self.context.tasks))
        downstream_tasks = set(self.flow.graph.downstream_tasks(self.context.tasks))

        return super().render(
            upstream_tasks=upstream_tasks.difference(self.context.tasks),
            downstream_tasks=downstream_tasks.difference(self.context.tasks),
            **kwargs,
        )


class TeamTemplate(Template):
    template_path: str = "team.md.jinja"
    team: Team
    context: AgentContext


class InstructionsTemplate(Template):
    template_path: str = "instructions.md.jinja"
    instructions: list[str] = []
    context: AgentContext

    def should_render(self) -> bool:
        return bool(self.instructions)
