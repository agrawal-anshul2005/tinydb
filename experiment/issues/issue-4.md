`tinydb.operations` provides `delete`, `set`, `add`, `subtract`, `increment`, and `decrement`, but migrating a field name across documents currently requires writing a custom callable.

Please add `rename(old_field: str, new_field: str)` to `tinydb/operations.py`:
- Moves the value at `doc[old_field]` to `doc[new_field]` and removes `old_field`.
- If `old_field == new_field` and the field exists, leave the document unchanged.
- If `new_field` already exists in the document, overwrite it with `doc[old_field]`'s value and remove `old_field`.
- If `old_field` is not present in the document, raise `KeyError` (consistent with `delete`, `add`, and `increment`).
