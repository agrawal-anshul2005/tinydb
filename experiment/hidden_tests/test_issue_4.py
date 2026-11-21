import pytest
from tinydb import TinyDB, where
from tinydb.storages import MemoryStorage


def test_rename_moves_value_and_removes_old_key():
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    db.insert({'fname': 'Alice', 'age': 30})
    db.insert({'fname': None, 'age': 25})

    db.update(rename('fname', 'first_name'), where('fname').exists())
    docs = db.all()
    assert docs == [
        {'first_name': 'Alice', 'age': 30},
        {'first_name': None, 'age': 25},
    ]


def test_rename_same_name_and_overwrite():
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    db.insert({'a': 1, 'b': 2})

    db.update(rename('a', 'a'))
    assert db.all() == [{'a': 1, 'b': 2}]

    db.update(rename('a', 'b'))
    assert db.all() == [{'b': 1}]


def test_rename_missing_field_raises_keyerror():
    from tinydb.operations import rename

    db = TinyDB(storage=MemoryStorage)
    db.insert({'other': 1})

    with pytest.raises(KeyError):
        db.update(rename('missing', 'new_name'))
