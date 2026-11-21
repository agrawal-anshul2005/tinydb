Hi! We use TinyDB in a small internal app where documents don't always have a strict schema. Sometimes a field is missing or set to `None` or a string where other documents have a number.

Right now, running range comparisons like `where('score') > 50` crashes with a `TypeError` as soon as it hits a document with `score: None` or `score: "N/A"`, instead of just skipping that document. Also, doing bulk cleanups with `operations.delete('temp')` blows up if some documents don't have `'temp'`.

Can TinyDB handle these messy documents more safely without breaking normal usage?
