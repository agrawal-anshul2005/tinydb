I ran into two issues when using `Query().<field>.fragment(...)` on a TinyDB table:

1. **Stale cached results across paths:** Searching `Query().a.fragment({'x': 1})` and then `Query().b.fragment({'x': 1})` on the same `TinyDB` table returns the cached result of the first query instead of evaluating path `b`. Also `Query().a.fragment({'x': 1}) == Query().b.fragment({'x': 1})` evaluates to `True`.
2. **Crash on non-mapping field values:** When a document has a non-dict value at that path (for example `{'a': None}` or `{'a': 42}`), evaluating `Query().a.fragment({'x': 1})` raises `TypeError: argument of type 'NoneType' is not iterable` instead of returning `False`.

Expected behavior:
- `fragment()` queries on different paths should have distinct hashes and never share query-cache entries.
- When the resolved field value is not a mapping (e.g., `None`, `int`, `list`, `str`), `fragment()` should return `False` without raising `TypeError`.
