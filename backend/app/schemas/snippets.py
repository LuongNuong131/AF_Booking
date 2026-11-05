from datetime import datetime

from pydantic import Field

from app.schemas.contracts import ContractModel


class NoteSnippet(ContractModel):
    id: int
    title: str
    text: str
    use_count: int
    created_at: datetime
    updated_at: datetime


class NoteSnippetCreate(ContractModel):
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1000)


class NoteSnippetPatch(ContractModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    text: str | None = Field(default=None, min_length=1, max_length=1000)


SNIPPET_MODELS = (NoteSnippet, NoteSnippetCreate, NoteSnippetPatch)
