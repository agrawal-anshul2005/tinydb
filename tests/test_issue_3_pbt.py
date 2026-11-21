import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from tinydb import TinyDB
from tinydb.storages import MemoryStorage
from tinydb.queries import Query
from hypothesis import HealthCheck as _AutoSEHealthCheck, settings as _autose_settings
_autose_settings.register_profile(
    'autose_pbt',
    max_examples=50,
    derandomize=True,
    deadline=None,
    suppress_health_check=list(_AutoSEHealthCheck),
)
_autose_settings.load_profile('autose_pbt')



@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    a=st.integers(min_value=-500, max_value=500),
    b=st.integers(min_value=-500, max_value=500),
    v=st.integers(min_value=-1000, max_value=1000)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_between_inclusive_integers(field_name, a, b, v):
    low, high = min(a, b), max(a, b)
    query = Query()[field_name].between(low, high)
    doc = {field_name: v}
    
    expected = (low <= v <= high)
    # In TinyDB, queries are tested against documents using doc(item) or db.search
    # Wait, the failure was: TypeError: QueryInstance.__call__() takes 2 positional arguments but 3 were given
    # Or query(doc). In TinyDB, query instances are called as query(doc). Let's check how Query is evaluated.
    # Actually, a Query object in TinyDB evaluates via query(doc). Let's use query(doc).
    assert query(doc) == expected


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    a=st.integers(min_value=-500, max_value=500),
    b=st.integers(min_value=-500, max_value=500),
    v=st.integers(min_value=-1000, max_value=1000)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_between_exclusive_integers(field_name, a, b, v):
    low, high = min(a, b), max(a, b)
    query = Query()[field_name].between(low, high, inclusive=False)
    doc = {field_name: v}
    
    expected = (low < v < high)
    assert query(doc) == expected


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    a=st.integers(min_value=-500, max_value=500),
    b=st.integers(min_value=-500, max_value=500),
    v=st.integers(min_value=-1000, max_value=1000)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_range_integers(field_name, a, b, v):
    low, high = min(a, b), max(a, b)
    query = Query()[field_name].between(low, high, inclusive=True)
    doc = {field_name: v}
    
    expected = (low <= v <= high)
    assert query(doc) == expected


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    low=st.integers(min_value=0, max_value=10),
    high=st.integers(min_value=11, max_value=20)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_pbt_missing_field(field_name, low, high):
    query = Query()[field_name].between(low, high)
    doc = {'other_field': 42}
    assert query(doc) is False


def test_ac1_and_ac2_inclusive_range():
    query = Query()['age'].between(18, 65, inclusive=True)
    
    assert query({'age': 18}) is True
    assert query({'age': 40}) is True
    assert query({'age': 65}) is True
    assert query({'age': 17}) is False
    assert query({'age': 66}) is False


def test_ac3_exclusive_range():
    query = Query()['age'].between(18, 65, inclusive=False)
    
    assert query({'age': 18}) is False
    assert query({'age': 65}) is False
    assert query({'age': 40}) is True


def test_ac4_unrooted_query_error():
    with pytest.raises(ValueError, match='Query has no path'):
        Query().between(1, 10)


def test_ac5_missing_field_or_incomparable_type():
    query = Query()['age'].between(18, 65)
    
    assert query({}) is False
    assert query({'age': 'forty'}) is False
    assert query({'age': None}) is False


def test_ac6_query_hash_distinction():
    q1 = Query()['age'].between(18, 65, inclusive=True)
    q2 = Query()['age'].between(18, 65, inclusive=False)
    
    assert hash(q1) != hash(q2)


def test_tiny_db_integration_with_range():
    db = TinyDB(storage=MemoryStorage)
    db.insert({'name': 'Alice', 'age': 25})
    db.insert({'name': 'Bob', 'age': 17})
    db.insert({'name': 'Charlie', 'age': 65})
    db.insert({'name': 'Diana', 'age': 70})

    res_inclusive = db.search(Query()['age'].between(18, 65))
    names_inclusive = {doc['name'] for doc in res_inclusive}
    assert names_inclusive == {'Alice', 'Charlie'}

    res_exclusive = db.search(Query()['age'].between(18, 65, inclusive=False))
    names_exclusive = {doc['name'] for doc in res_exclusive}
    assert names_exclusive == {'Alice'}
