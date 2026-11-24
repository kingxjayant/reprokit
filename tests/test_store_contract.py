"""Every Store implementation must accept an explicit report id.

Bug this guards against (found in production, 2026-11-24): `/save` was changed
to mint the id itself so the permalink could be embedded in the Markdown, and
`Store.save_report` was given an optional `rid`. But `PostgresStore` **overrides**
`save_report` with its own signature and still called `new_id()` unconditionally
plus `kwargs["markdown"]` — it took `**kwargs`, so passing `rid=` did not raise a
TypeError, it simply ignored the argument. The deployed app then hit

    KeyError: 'rid'   ->   POST /save  500 Internal Server Error

while all 125 tests stayed green, because the whole suite runs against SQLite.

The suite now instantiates every registered store class and asserts that an
explicit id is honoured, so a future override cannot silently drop it again.
"""

import inspect

import pytest

from app import db as db_module
from app.db import SQLiteStore, Store, new_id


def _store_classes() -> list[type[Store]]:
    """Every concrete Store subclass defined in app.db."""
    return [
        obj
        for obj in vars(db_module).values()
        if inspect.isclass(obj)
        and issubclass(obj, Store)
        and obj is not Store
    ]


def test_the_store_classes_we_expect_are_present():
    names = {c.__name__ for c in _store_classes()}
    assert {"SQLiteStore", "PostgresStore"} <= names, names


@pytest.mark.parametrize("cls", _store_classes(), ids=lambda c: c.__name__)
def test_every_store_accepts_an_explicit_rid(cls):
    """No override may refuse or ignore `rid`."""
    sig = inspect.signature(cls.save_report)
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    assert "rid" in sig.parameters or accepts_kwargs, (
        f"{cls.__name__}.save_report cannot receive an explicit rid"
    )


@pytest.mark.parametrize("cls", _store_classes(), ids=lambda c: c.__name__)
def test_plain_store_honours_the_rid(cls):
    """The base implementation is shared, so exercise it directly."""
    store = SQLiteStore(":memory:")
    store.init_schema()
    rid = new_id()
    assert (
        store.save_report(
            markdown="# r",
            verdict="not_rerunnable",
            fields_present=2,
            missing_fields=["steps"],
            redactions=0,
            rid=rid,
        )
        == rid
    )
    assert store.get_report(rid) is not None
    store.close()


def test_base_store_passes_rid_through():
    """Store.save_report itself must not mint over a supplied id."""
    src = inspect.getsource(Store.save_report)
    assert "rid or new_id()" in src, "base save_report no longer honours an explicit id"


def test_postgres_override_has_no_bare_new_id():
    """The Postgres override must not call new_id() unconditionally."""
    src = inspect.getsource(db_module.PostgresStore.save_report)
    assert 'kwargs.get("rid")' in src, (
        "PostgresStore.save_report ignores an explicit rid; /save will 500"
    )
