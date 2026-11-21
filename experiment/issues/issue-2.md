The docstring for `Query.one_of(items)` says:
> Check if the value is contained in a list or generator.

However, when passing a generator to `one_of()`, e.g.:
```python
db.search(Query().tag.one_of(x for x in ['a', 'b']))
```
the generator gets partially or fully exhausted on the first document(s), so subsequent matching documents in the table silently fail to match. Reusing the same `QueryInstance` a second time also fails.

Expected behavior:
- Passing any generator/iterator to `Query.one_of()` should match all qualifying documents in `db.search(...)` regardless of order or repeated evaluations.
- The resulting query should still be hashable and work safely with `Table`'s query cache (without colliding with a different set of items).
