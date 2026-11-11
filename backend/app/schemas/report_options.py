from datetime import date

from app.schemas.contracts import ContractModel


class ReportOptions(ContractModel):
    timezone: str
    today: date
    scopes: list[str]
    max_days: int = 366
