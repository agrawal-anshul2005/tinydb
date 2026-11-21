from tinydb import TinyDB, Query
from tinydb.storages import MemoryStorage


def test_one_of_with_generator_matches_all_docs():
    db = TinyDB(storage=MemoryStorage)
    db.insert_multiple([
        {'tag': 'b', 'id': 1},
        {'tag': 'a', 'id': 2},
        {'tag': 'c', 'id': 3},
        {'tag': 'b', 'id': 4},
        {'tag': 'a', 'id': 5},
    ])

    q = Query().tag.one_of(x for x in ['a', 'b'])
    matched = [d['id'] for d in db.search(q)]
    assert matched == [1, 2, 4, 5]


def test_one_of_generator_reusable_query():
    q = Query().val.one_of(i for i in range(3))
    assert q({'val': 2})
    assert q({'val': 0})
    assert q({'val': 2})
    assert not q({'val': 5})


def test_one_of_generator_hash_and_cache():
    db = TinyDB(storage=MemoryStorage)
    db.insert_multiple([{'n': 1}, {'n': 2}, {'n': 3}])

    q1 = Query().n.one_of(x for x in [1, 2])
    q2 = Query().n.one_of(x for x in [2, 3])
    assert hash(q1) != hash(q2)
    assert [d['n'] for d in db.search(q1)] == [1, 2]
    assert [d['n'] for d in db.search(q2)] == [2, 3]
