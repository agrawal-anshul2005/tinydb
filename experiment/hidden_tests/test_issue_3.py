import pytest
from tinydb import TinyDB, Query, where
from tinydb.storages import MemoryStorage


def test_between_inclusive_default():
    q = where('age').between(18, 65)
    assert q({'age': 18})
    assert q({'age': 40})
    assert q({'age': 65})
    assert not q({'age': 17})
    assert not q({'age': 66})


def test_between_exclusive():
    q = where('age').between(18, 65, inclusive=False)
    assert q({'age': 19})
    assert not q({'age': 18})
    assert not q({'age': 65})


def test_between_cache_distinguishes_inclusive_flag():
    db = TinyDB(storage=MemoryStorage)
    db.insert_multiple([{'x': 10}, {'x': 15}, {'x': 20}])

    q_inc = Query().x.between(10, 20, inclusive=True)
    q_exc = Query().x.between(10, 20, inclusive=False)

    assert q_inc != q_exc
    assert [d['x'] for d in db.search(q_inc)] == [10, 15, 20]
    assert [d['x'] for d in db.search(q_exc)] == [15]


def test_between_edge_cases():
    q = Query().x.between(1, 10)
    assert not q({})
    assert not q({'x': None})
    assert not q({'x': 'five'})

    with pytest.raises(ValueError):
        Query().between(1, 10)
