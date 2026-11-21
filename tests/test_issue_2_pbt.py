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



@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    items=st.lists(st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=5), min_size=0, max_size=5),
    doc_values=st.lists(st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=5), min_size=1, max_size=10)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_one_of_generator_equivalence(field_name, items, doc_values):
    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')

    for val in doc_values:
        table.insert({field_name: val})

    # Query with list
    q_list = Query()[field_name].one_of(items)
    res_list = table.search(q_list)

    # Query with generator
    q_gen = Query()[field_name].one_of(x for x in items)
    res_gen = table.search(q_gen)

    # Query with iterator
    q_iter = Query()[field_name].one_of(iter(items))
    res_iter = table.search(q_iter)

    assert res_list == res_gen
    assert res_list == res_iter


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    items=st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=5),
    doc_values=st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=10)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_one_of_generator_reusability(field_name, items, doc_values):
    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')

    for val in doc_values:
        table.insert({field_name: val})

    # Create a query instance using a generator
    query = Query()[field_name].one_of(x for x in items)

    # Execute search multiple successive times using the exact same query instance
    res1 = table.search(query)
    res2 = table.search(query)
    res3 = table.search(query)

    assert res1 == res2
    assert res2 == res3


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    items=st.lists(st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=5), min_size=1, max_size=5)
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_one_of_query_caching_and_hashability(field_name, items):
    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')
    table.insert({field_name: items[0]})

    q1 = Query()[field_name].one_of(x for x in items)
    q2 = Query()[field_name].one_of(items)

    assert q1.is_cacheable()
    assert q2.is_cacheable()
    assert hash(q1) == hash(q2)
    assert q1 == q2

    # Verify query cache utilization works correctly across searches
    res1 = table.search(q1)
    res2 = table.search(q1)
    assert res1 == res2


def test_one_of_empty_generator_boundary():
    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')
    table.insert({'tag': 'a'})
    table.insert({'tag': 'b'})

    q = Query()['tag'].one_of(x for x in [])
    results = table.search(q)
    assert results == []


def test_one_of_mixed_iterables_boundary():
    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')
    table.insert({'val': 1})
    table.insert({'val': 2})
    table.insert({'val': 3})

    # Tuple input
    q_tuple = Query()['val'].one_of((1, 2))
    # Set input
    q_set = Query()['val'].one_of({1, 2})
    # Generator input
    q_gen = Query()['val'].one_of(x for x in [1, 2])

    assert table.search(q_tuple) == table.search(q_set)
    assert table.search(q_set) == table.search(q_gen)
    assert len(table.search(q_gen)) == 2
