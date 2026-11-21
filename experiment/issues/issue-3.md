Range queries currently require repeating the field path twice:
```python
db.search((where('age') >= 18) & (where('age') <= 65))
```

Please add a `between(low, high, inclusive=True)` method to `Query` in `tinydb/queries.py`:
- When `inclusive=True` (default), match values where `low <= value <= high`.
- When `inclusive=False`, match values where `low < value < high`.
- Follow existing `Query` conventions: raise `ValueError('Query has no path')` if called on an empty `Query()`, return `False` when the field is missing or incomparable with `low`/`high` (e.g., `None` or a string compared to numbers), and include the path, bounds, and `inclusive` flag in the query hash so `Table`'s query cache never mixes inclusive and exclusive results.
