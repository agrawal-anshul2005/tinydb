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
    field_a=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    field_b=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_key=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_val=st.integers(min_value=-1000, max_value=1000),
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_fragment_path_disambiguation_pbt(field_a, field_b, frag_key, frag_val):
    if field_a == field_b:
        return

    q1 = Query()[field_a].fragment({frag_key: frag_val})
    q2 = Query()[field_b].fragment({frag_key: frag_val})

    # AC-1 / FR-1 / FR-2: Queries on different paths must not be equal and must have distinct hashes
    assert q1 != q2
    assert hash(q1) != hash(q2)


@given(
    field_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_key=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_val=st.integers(min_value=-1000, max_value=1000),
    non_mapping_val=st.one_of(
        st.none(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', max_size=10),
        st.lists(st.integers(), max_size=3),
    ),
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_fragment_non_mapping_evaluation_pbt(field_name, frag_key, frag_val, non_mapping_val):
    q = Query()[field_name].fragment({frag_key: frag_val})
    doc = {field_name: non_mapping_val}

    # AC-3, AC-4 / FR-3: Evaluating fragment on non-mapping values must return False without raising TypeError
    assert q(doc) is False


@given(
    field_a=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    field_b=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_key=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8),
    frag_val=st.integers(min_value=-1000, max_value=1000),
)
@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))
def test_table_query_cache_disambiguation_pbt(field_a, field_b, frag_key, frag_val):
    if field_a == field_b:
        return

    db = TinyDB(storage=MemoryStorage)
    table = db.table('test')

    # Insert document matching path 'a' but not path 'b'
    doc = {field_a: {frag_key: frag_val}, field_b: {frag_key: frag_val + 1}}
    table.insert(doc)

    q_a = Query()[field_a].fragment({frag_key: frag_val})
    q_b = Query()[field_b].fragment({frag_key: frag_val})

    res_a = table.search(q_a)
    res_b = table.search(q_b)

    # AC-2: Executing second query after first must not return cached results from path a
    assert len(res_a) == 1
    assert len(res_b) == 0


def test_fragment_boundary_equality_and_hashes():
    q1 = Query().fragment({'x': 1})
    q2 = Query().a.fragment({'x': 1})
    q3 = Query().b.fragment({'x': 1})

    assert q2 != q3
    assert hash(q2) != hash(q3)
    assert q1 != q2


def test_fragment_boundary_non_mapping_types():
    q = Query().a.fragment({'x': 1})

    for val in [None, 42, 3.14, 'string', [1, 2], True, False]:
        doc = {'a': val}
        assert q(doc) is False


def test_fragment_boundary_mapping_match():
    q = Query().a.fragment({'x': 1})
    doc = {'a': {'x': 1, 'y': 2}}

    # AC-5 / FR-4: Matching mapping value returns True
    assert q(doc) is True
