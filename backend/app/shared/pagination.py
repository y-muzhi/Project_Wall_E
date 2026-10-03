"""SHR-PAGE arithmetic only; repositories must still prove consistent read snapshots."""

from .validation import strict_integer

PAGE_SIZE = 20
MAX_PAGE = 100_000


def page_number(value: object = 1) -> int:
    return strict_integer(value, "page", maximum=MAX_PAGE)


def page_metadata(page: int, total: int) -> dict[str, int]:
    page = page_number(page)
    total = strict_integer(total, "total", minimum=0)
    return {"page": page, "page_size": PAGE_SIZE, "total": total, "total_pages": (total + PAGE_SIZE - 1) // PAGE_SIZE}


def page_offset(page: int) -> int:
    return (page_number(page) - 1) * PAGE_SIZE
