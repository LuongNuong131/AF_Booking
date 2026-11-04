from typing import Annotated

from fastapi import Path

Identifier = Annotated[int, Path(ge=1, le=18446744073709551615)]
KeyPath = Annotated[str, Path(min_length=1, max_length=100)]
