"""Errors raised by the domain and application layers.

Each class names one kind of failure, so an API adapter can map it to a single
HTTP status: NotFound 404, NotAuthorized 403, InvalidState and Duplicate 409,
InvalidData 422. Each also extends the built-in exception with the same meaning.
"""


class SillycationError(Exception):
    """Base class of every Sillycation domain or application error."""


class NotFound(SillycationError, LookupError):
    """A requested aggregate or entity does not exist."""


class NotAuthorized(SillycationError, PermissionError):
    """The acting user is not allowed to perform the operation."""


class InvalidState(SillycationError, ValueError):
    """The operation is not allowed in the current lifecycle state."""


class Duplicate(SillycationError, ValueError):
    """An identity, a unique value or a one-time action already exists."""


class InvalidData(SillycationError, ValueError):
    """The supplied or stored data violates a validation rule."""
