# Реэкспорт: старые импорты "from app.infrastructure import nn_pipeline"
# продолжают работать после выноса логики в app/core/nn_pipeline.py
from app.core.nn_pipeline import (  # noqa: F401
    generate_response,
    generate_annotation,
    generate_response_full,
)
