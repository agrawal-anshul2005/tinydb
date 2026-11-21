import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from tinydb import TinyDB, Query
from tinydb.storages import MemoryStorage
from hypothesis import HealthCheck as _AutoSEHealthCheck, settings as _autose_settings
_autose_settings.register_profile(
    'autose_pbt',
    max_examples=50,
    derandomize=True,
    deadline=None,
    suppress_health_check=list(_AutoSEHealthCheck),
)
_autose_settings.load_profile('autose_pbt')



# ==========================================
# Property-Based Tests (Hypothesis)
# ==========================================

@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    val=st.one_of(
        st.integers(min_value=-1000, max_value=1000),
        st.text(alphabet='abcdef012345', max_size=12),
        st.booleans()
    )
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_rename_roundtrip(field_name, val):
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({field_name: val})

    temp_field = "tempfield"
    # Ensure temp_field doesn't collide with field_name in the test setup if by chance they are equal
    if field_name == temp_field:
        return

    # Rename field_name -> temp_field -> field_name
    db.update(rename(field_name, temp_field), doc_ids=[doc_id])
    db.update(rename(temp_field, field_name), doc_ids=[doc_id])

    doc = db.get(doc_id=doc_id)
    assert doc[field_name] == val
    assert temp_field not in doc
    db.close()


@given(
    old_f=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=6),
    new_f=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=6),
    val=st.integers(min_value=-100, max_value=100)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_rename_invariants(old_f, new_f, val):
    from tinydb.operations import rename

    if old_f == new_f:
        return

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({old_f: val})

    db.update(rename(old_f, new_f), doc_ids=[doc_id])

    doc = db.get(doc_id=doc_id)
    assert old_f not in doc
    assert doc[new_f] == val
    db.close()


@given(
    missing_f=st.text(alphabet='xyz', min_size=1, max_size=4),
    target_f=st.text(alphabet='abc', min_size=1, max_size=4)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_rename_missing_field_raises(missing_f, target_f):
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    # Ensure missing_f is genuinely not in the document
    doc_id = db.insert({target_f: 42})
    if missing_f == target_f:
        return

    with pytest.raises(KeyError):
        db.update(rename(missing_f, target_f), doc_ids=[doc_id])

    db.close()


# ==========================================
# Example-Based Boundary Tests (AC-1 to AC-4)
# ==========================================

def test_ac1_standard_rename():
    """AC-1: Given a document {'a': 1} and the operation rename('a', 'b'),
    When the operation is applied, Then the resulting document is {'b': 1} without key 'a'."""
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({'a': 1})

    db.update(rename('a', 'b'), doc_ids=[doc_id])
    doc = db.get(doc_id=doc_id)

    assert doc == {'b': 1}
    assert 'a' not in doc
    db.close()


def test_ac2_rename_to_self():
    """AC-2: Given a document {'a': 1} and the operation rename('a', 'a'),
    When the operation is applied, Then the resulting document is {'a': 1}."""
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({'a': 1})

    db.update(rename('a', 'a'), doc_ids=[doc_id])
    doc = db.get(doc_id=doc_id)

    assert doc == {'a': 1}
    db.close()


def test_ac3_rename_overwriting_existing():
    """AC-3: Given a document {'a': 1, 'b': 2} and the operation rename('a', 'b'),
    When the operation is applied, Then the resulting document is {'b': 1}."""
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({'a': 1, 'b': 2})

    db.update(rename('a', 'b'), doc_ids=[doc_id])
    doc = db.get(doc_id=doc_id)

    assert doc == {'b': 1}
    assert 'a' not in doc
    db.close()


def test_ac4_rename_missing_field_raises():
    """AC-4: Given a document {'b': 2} and the operation rename('a', 'b'),
    When the operation is applied, Then a KeyError is raised."""
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    doc_id = db.insert({'b': 2})

    with pytest.raises(KeyError):
        db.update(rename('a', 'b'), doc_ids=[doc_id])

    db.close()


def test_export_in_operations_and_module():
    """FR-1: Verify rename is correctly exposed in tinydb.operations."""
    import tinydb.operations
    assert hasattr(tinydb.operations, 'rename')
    assert callable(tinydb.operations.rename('a', 'b'))
