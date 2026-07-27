"""Stage-one baseline metric calculation and JSON persistence."""

import json
from pathlib import Path

from app.core.logging import get_logger
from app.models.domain import RunMetrics, TextMessage

logger = get_logger(__name__)


def estimate_tokens(character_count: int) -> int:
    """Estimate tokens consistently without calling a tokenizer service."""

    if character_count <= 0:
        return 0
    return (character_count + 3) // 4


class MetricsWriter:
    """Persist one JSON metric artifact for every completed task."""

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir

    def save(
        self,
        task_id: str,
        elapsed_ms: float,
        messages: list[TextMessage],
    ) -> RunMetrics:
        """Calculate and atomically save communication baseline metrics."""

        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        character_count = sum(len(message.content) for message in messages)
        destination = self._metrics_dir / f"{task_id}.json"
        metrics = RunMetrics(
            elapsed_ms=round(max(elapsed_ms, 0.0), 3),
            message_count=len(messages),
            character_count=character_count,
            estimated_token_count=estimate_tokens(character_count),
            metrics_file=str(destination),
        )
        payload = {
            "task_id": task_id,
            "communication_mode": "text",
            **metrics.model_dump(mode="json"),
        }
        temporary = destination.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError as exc:
            logger.exception("Unable to persist metrics for task %s", task_id)
            raise RuntimeError(f"Unable to save metrics: {exc}") from exc
        logger.info("Saved task %s metrics to %s", task_id, destination)
        return metrics
