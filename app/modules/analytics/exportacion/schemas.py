"""Export-specific extension of the shared report definition."""

from typing import Literal

from ..reportes.schemas import QueryRequest


class ExportRequest(QueryRequest):
    formato: Literal["pdf", "xlsx", "csv", "html"]
