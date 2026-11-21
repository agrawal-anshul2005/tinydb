from tinydb import TinyDB, where
from tinydb.storages import MemoryStorage


def test_ordering_comparisons_skip_incomparable_types():
    db = TinyDB(storage=MemoryStorage)
    db.insert_multiple([
        {'name': 'ok', 'score': 80},
        {'name': 'low', 'score': 20},
        {'name': 'null', 'score': None},
        {'name': 'str', 'score': 'N/A'},
        {'name': 'missing'},
    ])

    assert [d['name'] for d in db.search(where('score') > 50)] == ['ok']
    assert [d['name'] for d in db.search(where('score') < 50)] == ['low']
    assert [d['name'] for d in db.search(where('score') >= 80)] == ['ok']
    assert [d['name'] for d in db.search(where('score') <= 20)] == ['low']


def test_normal_string_and_numeric_comparisons_still_work():
    assert (where('s') > 'a')({'s': 'b'})
    assert not (where('s') < 'a')({'s': 'b'})
    assert (where('n') <= 10)({'n': 10})
