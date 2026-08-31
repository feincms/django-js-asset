# Spec: aligning `js_asset` assets with Django's `MediaAsset` family

Status: **implemented** (approach C, metaclass variant). `JS`/`CSS` now produce
Django `Script`/`Stylesheet`/`InlineStyle`; `_compat.py` backports the family
(6.2 contract) below 5.2/6.1; `media.py` renders the nonce generically. The
whole tox matrix (4.2 → main) is green.

Correction found during implementation (the matrix below has been updated
accordingly): `Stylesheet` and `MediaAsset.render(*, attrs=)` actually landed in
**Django 6.1**, not 6.2. Only `Media`'s bare-string auto-wrapping and the
attribute-aware `__eq__`/`__hash__` are 6.2-only. This does not change the
design: 5.2/6.0 still lack `Stylesheet` and `render(attrs=)`, so the backport
and generic nonce rendering are still required, and equality is still path-only
across 5.2–6.1.

## Goal

`js_asset` ships `JS`, `CSS`, `JSON`, `ImportMap` media objects. The first two
predate Django's own object-based media assets (`MediaAsset`, `Script`,
`Stylesheet`). We want to move *towards* Django: ideally `JS`/`CSS` should be —
or behave indistinguishably from — Django's `Script`/`Stylesheet`, so that the
two interoperate cleanly in `forms.Media.merge()` and so that `js_asset` can
eventually shrink to a thin compatibility shim.

The original framing ("make `CSS`/`JS` constructor functions that return
`Script`/`Stylesheet`") turns out to be the wrong shape; the viable shape is
**subclassing** `Script`/`Stylesheet`, with backports for older Django. The
sticking points are (a) the version availability matrix and (b) the equality
contract, which Django itself changed between releases.

## What exists where (verified against the Django source tree)

`MediaAsset`/`Script` were added in **Django 5.2** (ticket #35886).
`Stylesheet` and the `render(*, attrs=...)` method arrived in **Django 6.1**.
`Media`'s auto-wrapping of bare path strings into assets, and the
attribute-aware equality, arrived in **Django 6.2**. `js_asset`'s support floor
is **Django 4.2**.

| Capability                                            | 4.2 – 5.1 | 5.2 / 6.0          | 6.1            | 6.2+ |
|-------------------------------------------------------|:---------:|:------------------:|:--------------:|:----:|
| `MediaAsset`, `Script`                                | ✗         | ✓                  | ✓              | ✓    |
| `Stylesheet`                                          | ✗         | ✗                  | ✓              | ✓    |
| `MediaAsset.render(*, attrs=)`                        | ✗         | ✗ (`__str__` only) | ✓              | ✓    |
| `__eq__` compares **attributes**                      | –         | no (path only)     | no (path only) | yes  |
| `__hash__`                                            | –         | `hash(_path)`      | `hash(_path)`  | `hash(_path) ^ hash(attrs)` |
| `Media` wraps bare strings → `Script`/`Stylesheet`    | ✗         | ✗                  | ✗              | ✓    |

Two consequences fall straight out of this table:

1. A factory that *returns* `Script`/`Stylesheet` needs those classes to exist —
   they don't below 5.2 (`Script`) / 6.1 (`Stylesheet`). So below those floors a
   **backport** must stand in (`_compat.py`). The remaining cost is that
   `isinstance(x, JS)` no longer works for the produced object; this is
   addressable (see the isinstance inventory and mitigations below) and turns
   out to be the *right* trade — see "the decisive finding".

2. Django's own equality contract is **not stable across versions**: 5.2–6.1
   dedup on the path alone (attributes ignored), 6.2 folds attributes back into
   identity. The bare-string equality (`Script("a.js") == "a.js"`) is present in
   all versions. Producing native objects means we inherit each version's
   contract as-is — which, given we design for 6.2 and "are reasonable" below, is
   acceptable rather than something to paper over.

## Current `js_asset` equality semantics (for contrast)

`JS`/`CSS`/`JSON` are `@dataclass(eq=True)` with `__hash__ = hash(str(self))`:

- `__eq__` compares **all** fields (src + attrs + media/inline).
- `__hash__` hashes the **rendered HTML**, so it is unequal to a bare path
  string and unequal to a Django `Script`/`Stylesheet` for the same file.

Net effect: in `Media.merge()`, `JS("a.js")`, the string `"a.js"`, and (on 6.2)
the auto-wrapped `Script("a.js")` are three *distinct* nodes → **the same file
renders up to three times.** This is the concrete interop bug we want to kill.

The user has confirmed that downstream packages which relied on the *old*
"attributes are part of identity, no string-equality" behaviour have already
been migrated, so **matching Django's path-based dedup is acceptable**.

## Existing scaffolding

`js_asset/_compat.py` already exists but is **not imported anywhere**. It
backports `MediaAsset` + `Script` for Django < 5.2, using path-only `__eq__`
/`__hash__` plus string equality (the 5.2 semantics). It does **not** yet
backport `Stylesheet`, `render(attrs=)`, or the 6.2 attribute-aware equality.

## The decisive finding: equality is by **class identity**, not `isinstance`

Django 6.2's `MediaAsset.__eq__` opens with:

```python
self.__class__ is other.__class__ and self._path == ... and self.attributes == ...
```

This is **strict class identity**, and it determines which "way forward" is real:

- On 6.2, `Media._normalize_js` auto-wraps a bare `"a.js"` into a **native**
  `Script("a.js")`. The most common interop case is therefore a native `Script`
  meeting one of our assets for the same file.
- A **subclass** `JS(Script)` has `__class__ is JS`; the wrapped string has
  `__class__ is Script`. `JS is not Script` ⇒ **not equal** ⇒ `merge()` renders
  the file twice. We cannot patch around it from our side: `Script.__eq__(js)`
  returns `False` (a real bool, not `NotImplemented`), so Python never consults
  our reflected `JS.__eq__` (the symmetry trap, here load-bearing).
- The **only** way our asset reliably dedups against Django's own `Script` —
  *and* against bare strings, via the `isinstance(other, str)` branch — is to be
  the **same class**: `JS(...)` must *produce an actual `Script`*.

So the equality convergence the user noticed (6.2 now compares `attributes`,
same sorted `flatatt`) does not make subclassing viable; it makes **becoming the
class** both viable and necessary for true dedup.

## Inventory of `isinstance`/type checks (does the factory break anything?)

All sites that touch these types live in `js_asset/media.py`:

| Site | Check | Under "factory" (`JS`/`CSS` produce Django assets) |
|------|-------|-----------------------------------------------------|
| `:100`, `:107` | `isinstance(x, ImportMap)` | ✓ `ImportMap` stays a class |
| `:109` | `JS(item) if isinstance(item, str)` | ✓ calls the factory |
| `:117` | `CSS(item, media=medium) if isinstance(item, str)` | ✓ calls the factory |
| `:123` | `isinstance(asset, (CSS, JS, JSON, ImportMap))` | ✗ **TypeError** — `CSS`/`JS` are no longer classes |

Exactly **one** line breaks, and it is ours. It only exists to choose a render
convention (`render(nonce=)` for our objects vs `render(attrs=)` for Django's);
it becomes `isinstance(asset, (MediaAsset, JSON, ImportMap))` and the nonce is
injected generically. The only *external* casualty is user code doing
`isinstance(x, JS)` — addressable, see options below.

## Approaches considered

### A. Equality interop only (minimal)

Keep the dataclasses; give `JS`/`CSS` Django's string-equality + path-hash. Fixes
dedup **against bare strings** on all versions, but — per the class-identity
finding — still does **not** dedup against a native 6.2 `Script`. Smallest
change, weakest result, no movement toward Django types.

### B. Subclass `Script`/`Stylesheet`

`isinstance(x, JS)` keeps working and they look Django-native, **but** the
class-identity equality check means a `JS` and a native `Script` for the same
path do *not* merge on 6.2. Rejected as the primary path: it fails the exact
case 6.2 makes most common.

### C. `JS`/`CSS` *produce* Django `Script`/`Stylesheet` (recommended)

```
JS(src, attrs)  -> Script(src, **attrs)          # native on 5.2+, backport below
CSS(src, ...)   -> Stylesheet(...) | InlineStyle  # native Stylesheet on 6.2+
JSON, ImportMap -> stay custom @html_safe classes
```

- The produced object **is** a `Script`/`Stylesheet`, so it shares merge buckets
  with native Django assets *and* bare strings — full dedup, including 6.2's
  auto-wrapped strings.
- This is the cleanest on-ramp to eventually deleting js_asset's classes: on 6.2
  `JS(...)` already yields a stdlib object.
- Costs: `isinstance(x, JS)` (external), inline CSS, and nonce rendering on
  5.2–6.1 — all detailed below.

`JS`/`CSS` can be plain functions, or thin classes with a metaclass whose
`__call__` returns the Django object and whose `__instancecheck__` delegates to
`isinstance(x, Script)` — the latter keeps `isinstance(x, JS)` truthy at the cost
of a little machinery.

## Version strategy: solve 6.2 well, be reasonable below

The attribute-aware equality only exists from 6.2, so **6.2+ is the target we
design for** and older versions get a pragmatic best effort rather than a
bit-for-bit match:

- **6.2+** — `JS`/`CSS` produce native `Script`/`Stylesheet`; nonce flows through
  `render(attrs={"nonce": ...})`; dedup, byte-identity and the `csp_nonce_attr`
  tag all work natively. This path gets the polish and the thorough tests.
- **5.2 – 6.1** — native `Script` exists (so JS-produced scripts still dedup with
  strings/native Scripts via path), and equality is path-only throughout this
  band. 5.2/6.0 additionally lack `Stylesheet` and `render(attrs=)` (the
  backport supplies `Stylesheet`); 6.1 has both natively. Either way we let
  js_asset's `Media` do the nonce rendering itself (rebuild the tag from
  `element_template` + `flatatt`) rather than depend on `render(attrs=)`.
- **4.2 – 5.1** — no Django asset classes at all; the `_compat.py` backport
  stands in. Goal here is "correct and reasonable", not feature-matched.

## Detailed design for approach C

### Constructor translation (the "easy" part)

`js_asset` keeps its historic signatures; the factory forwards into the
`**attributes` base and returns the Django object:

```python
def JS(src, attrs=None):
    return Script(src, **(attrs or {}))


def CSS(src, media="all", *, inline=False):
    if inline:
        return InlineStyle(src, media=media)  # see "inline CSS" below
    return Stylesheet(src, media=media)
```

Note: `attrs` keys like `data-the-answer` are not valid Python identifiers, so
they must flow through `**{...}`, never literal kwargs — already the case here.

### Rendering & byte-identity

Both `js_asset` and Django route attributes through the **same**
`django.forms.utils.flatatt`, which **sorts** attributes alphabetically. For the
common cases this makes the output byte-identical:

- `JS("a.js", {...})` and `Script("a.js", **{...})` →
  `<script src=... data-the-answer="42" id="asset-script"></script>` (identical).
- `CSS("a.css", media="all")` and `Stylesheet("a.css", media="all")` →
  `<link href=... media="all" rel="stylesheet">` (identical, including the
  `nonce` slot which sorts between `media` and `rel`).

The existing exact-string tests (`test_css`, `test_json`,
`test_boolean_attributes`, `test_asset`) are therefore expected to keep passing,
which satisfies the AGENTS.md byte-identity constraint — **but this must be
re-verified per supported Django version**, because the base class differs.

### Nonce rendering (the part that varies by version)

`js_asset` historically renders the nonce itself (so it works on 4.2). Django
6.2 renders it via `asset.render(attrs={"nonce": ...})`; 5.2–6.1 assets have only
`__str__`; <5.2 has no asset class.

Because we produce **native** objects on 6.2+, the clean path there is to let
Django render: `media.render(attrs={"nonce": nonce})` is exactly what the
built-in `csp_nonce_attr` tag does, and our `Media.render()` already forwards
`attrs`. On 5.2–6.1 (and via the backport on <5.2) js_asset's `Media` renders the
nonce by rebuilding the tag from the asset's `element_template` and
`flatatt({**asset.attributes, "nonce": nonce})` — the asset itself stays a plain
native `Script`. This keeps the *asset* objects pure Django and confines the
version-specific logic to js_asset's `Media._render_asset`.

`JSON` / `ImportMap` keep their own `render(*, nonce=...)` (they are not
`MediaAsset`s).

### Equality / hash — inherited, not reimplemented

Because `JS`/`CSS` *produce* `Script`/`Stylesheet`, equality and hashing are
**Django's**, version-appropriate by construction — we write none of it on 6.2+.
Consequences, all acceptable per the recorded decision to "match Django":

- 6.2+: path + attributes identity, plus the bare-string branch. A path with
  differing attributes is a distinct asset; a path vs the same bare string
  dedups. Verified against existing tests: `test_set` → 2, `test_asset_merging`
  → 3 still hold.
- 5.2–6.1: path-only identity (attributes ignored) — slightly looser dedup than
  6.2, accepted under "be reasonable on older Django".
- The backport (<5.2) should mirror **6.2** semantics so the floor matches the
  target rather than the awkward middle.

### The hard problems (call out explicitly)

1. **Inline CSS has no Django equivalent.** `CSS(src, inline=True)` renders a
   `<style>…</style>` block whose `src` is *CSS text*, not a path; `Stylesheet`
   always renders `<link>` and runs `_path` through `static()`. So `CSS` is a
   factory that returns a small dedicated `InlineStyle(MediaAsset)` with a
   `<style media="{...}"{attributes}>{path}</style>` template and a `path`
   override that returns the source verbatim. It is still a `MediaAsset`, so it
   flows through the same render path; its `_path`-keyed equality is on CSS text,
   which is odd but harmless (inline blocks are rarely deduped).

2. **`JSON` and `ImportMap` stay custom.** No Django counterpart
   (`json_script` / `<script type="importmap">`). They remain standalone
   `@html_safe` classes; only `JS`/`CSS` produce Django assets.

3. **`isinstance(x, JS)` in user code breaks** if `JS`/`CSS` are plain functions.
   Two mitigations: (a) document that callers should test `Script`/`Stylesheet`
   /`MediaAsset`; or (b) make `JS`/`CSS` classes with a metaclass whose
   `__call__` returns the Django object and whose `__instancecheck__` delegates
   to `isinstance(x, Script)`. Decide based on how much external code relies on
   the check.

4. **5.2–6.1 native `Script` has no `render(attrs=)`.** `media.py:_render_asset`
   must not assume it; render the nonce via `element_template`/`flatatt` (above)
   and fall back to `str(asset)`/`__html__()` when no usable `render` exists.

## Recommendation

Pursue **C** — `JS`/`CSS` *produce* Django `Script`/`Stylesheet`. It is the only
approach that delivers true dedup with native 6.2 assets (the class-identity
finding rules out subclassing), and it is the cleanest path to eventually
retiring js_asset's own classes. Design for **6.2+ first**; treat 5.2–6.1 and
4.2–5.1 as "correct and reasonable", not bit-for-bit.

Sequence:

1. Extend `_compat.py`: add a `Stylesheet` backport and give the backport
   `MediaAsset` the 6.2 contract (`render(*, attrs=)`, attribute-aware
   `__eq__`/`__hash__`). On 5.2+ keep importing Django's own classes.
2. Turn `JS`/`CSS` into factories producing `Script`/`Stylesheet`
   (`+ InlineStyle` for inline CSS). Decide the `isinstance` mitigation.
3. Keep `JSON` / `ImportMap` standalone.
4. Rework `media.py:_render_asset`: drop `CSS`/`JS` from the type tuple, render
   the nonce for any `MediaAsset` generically, fall back to `str()`.
5. Run the exact-string tests across the **full tox matrix** (4.2 → 6.2). Spend
   the byte-identity effort on 6.2; accept reasonable differences below it.

## Open questions

- `isinstance(x, JS)`: drop it (document `Script`/`Stylesheet`) or preserve it
  with an `__instancecheck__` metaclass? Depends on real-world usage.
- Backport equality: mirror 6.2 (attribute-aware) — agreed — but confirm we are
  comfortable that 5.2–6.1 (native, path-only) is intentionally looser than both
  the floor and the target.
- Long-term: do we deprecate the `JS`/`CSS` names in favour of re-exporting
  Django's `Script`/`Stylesheet`, keeping only `JSON`/`ImportMap`/`Media`?
