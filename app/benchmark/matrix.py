"""Formal stage-three experiment matrix."""

from app.benchmark.models import ExperimentDefinition, ExperimentName
from app.models import CommunicationMode


EXPERIMENT_MATRIX: tuple[ExperimentDefinition, ...] = (
    ExperimentDefinition(
        name=ExperimentName.TEXT,
        communication_mode=CommunicationMode.TEXT,
        enable_shared_memory=True,
        enable_semantic_state=False,
        enable_result_reference=False,
    ),
    ExperimentDefinition(
        name=ExperimentName.STRUCTURED,
        communication_mode=CommunicationMode.STRUCTURED,
        enable_shared_memory=True,
        enable_semantic_state=True,
        enable_result_reference=True,
    ),
    ExperimentDefinition(
        name=ExperimentName.STRUCTURED_NO_MEMORY,
        communication_mode=CommunicationMode.STRUCTURED,
        enable_shared_memory=False,
        enable_semantic_state=True,
        enable_result_reference=True,
    ),
    ExperimentDefinition(
        name=ExperimentName.STRUCTURED_NO_SEMANTIC_STATE,
        communication_mode=CommunicationMode.STRUCTURED,
        enable_shared_memory=True,
        enable_semantic_state=False,
        enable_result_reference=True,
    ),
    ExperimentDefinition(
        name=ExperimentName.STRUCTURED_NO_RESULT_REF,
        communication_mode=CommunicationMode.STRUCTURED,
        enable_shared_memory=True,
        enable_semantic_state=True,
        enable_result_reference=False,
    ),
)


def select_experiments(selector: str) -> list[ExperimentDefinition]:
    """Resolve a CLI selector without silently accepting unknown names."""

    normalized = selector.strip().lower()
    if normalized in {"all", "ablation"}:
        return [item.model_copy(deep=True) for item in EXPERIMENT_MATRIX]
    selected = [
        item.model_copy(deep=True)
        for item in EXPERIMENT_MATRIX
        if item.name.value == normalized
    ]
    if not selected:
        choices = ", ".join(
            ["all", "ablation", *(item.name.value for item in EXPERIMENT_MATRIX)]
        )
        raise ValueError(
            f"Unknown experiment {selector!r}; choose one of: {choices}"
        )
    return selected

