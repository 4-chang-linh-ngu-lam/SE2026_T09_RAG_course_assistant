from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metadata(Input):
    title: NonBlank = Field(max_length=200)
    description: str = Field(default="", max_length=4000)
    expected_revision: int = Field(ge=1)


class Revision(Input):
    expected_revision: int = Field(ge=0)


class Deletion(Revision):
    confirmed_shared_class_count: int = Field(ge=0)


class Sharing(Revision):
    class_ids: list[UUID] = Field(min_length=1, max_length=50)


class Retry(Input):
    expected_generation: int = Field(ge=0)


class NewNote(Input):
    version: int = Field(gt=0)
    locator_id: str = Field(pattern=r"^[1-9][0-9]{0,3}$")
    note_text: NonBlank = Field(max_length=10000)
    source_quote: str | None = Field(default=None, max_length=2000)
    client_request_id: UUID


class EditNote(Revision):
    note_text: NonBlank = Field(max_length=10000)


class BookmarkState(Input):
    bookmarked: bool
