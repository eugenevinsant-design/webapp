# Реэкспорт: старые импорты "from app.infrastructure import nn_pipeline"
# продолжают работать после выноса логики в app/core/nn_pipeline.py
from app.core.nn_pipeline import generate_response, generate_annotation  # noqa: F401
