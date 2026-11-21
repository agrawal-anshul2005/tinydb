from tinydb import TinyDB, Query
from tinydb.storages import MemoryStorage


def test_fragment_cache_isolated_by_path():
    db = TinyDB(storage=MemoryStorage)
    db.insert({'a': {'x': 1}, 'b': {'x': 2}, 'name': 'first'})
    db.insert({'a': {'x': 2}, 'b': {'x': 1}, 'name': 'second'})

    q_a = Query().a.fragment({'x': 1})
    q_b = Query().b.fragment({'x': 1})

    assert q_a != q_b
    assert [d['name'] for d in db.search(q_a)] == ['first']
    assert [d['name'] for d in db.search(q_b)] == ['second']


def test_fragment_non_mapping_field_returns_false():
    q = Query().a.fragment({'x': 1})
    assert not q({'a': None})
    assert not q({'a': 42})
    assert not q({'a': ['x']})
    assert not q({'a': 'x'})


def test_fragment_root_and_nested_still_match():
    assert Query().fragment({'x': 1})({'x': 1, 'y': 2})
    assert Query().a.fragment({'x': 1})({'a': {'x': 1, 'y': 2}})
    assert not Query().a.fragment({})({'a': None})
    assert Query().a.fragment({})({'a': {'x': 1}})
