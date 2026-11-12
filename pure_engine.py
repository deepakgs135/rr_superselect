"""Pure-Python DataFrame, Series, NumPy, and Plotly Express engine for app.py.

Uses only Python standard library modules (csv, math, re, datetime, collections)
and plotly.graph_objects (pure Python), avoiding compiled C-extensions (.pyd)
that Windows Smart App Control / Application Control can block.
"""
from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import plotly.graph_objects as go

NAN = float("nan")


def is_na(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def not_na(v: Any) -> bool:
    return not is_na(v)


def _try_num(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v).strip()
    if s == "":
        return NAN
    low = s.lower()
    if low == "nan" or low == "none":
        return NAN
    try:
        if "." not in s and "e" not in low:
            return int(s)
        return float(s)
    except ValueError:
        return s


def _to_float(v: Any) -> float:
    if is_na(v):
        return NAN
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return NAN


class Row(dict):
    """Dictionary row supporting attribute access, .iloc, and .get."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def iloc(self):
        vals = list(self.values())
        return _IlocList(vals)


class _IlocList:
    def __init__(self, items: list[Any]):
        self._items = items

    def __getitem__(self, idx: int) -> Any:
        return self._items[idx]


class _StrAccessor:
    def __init__(self, s: Series):
        self._s = s

    def lower(self) -> Series:
        return Series(["" if is_na(x) else str(x).lower() for x in self._s._data])

    def strip(self) -> Series:
        return Series(["" if is_na(x) else str(x).strip() for x in self._s._data])

    def contains(self, pat: str, regex: bool = True, na: bool = False) -> Series:
        if regex:
            rx = re.compile(pat, re.IGNORECASE)
            return Series([na if is_na(x) else bool(rx.search(str(x))) for x in self._s._data])
        sub = pat.lower()
        return Series([na if is_na(x) else (sub in str(x).lower()) for x in self._s._data])


class _DtAccessor:
    def __init__(self, s: Series):
        self._s = s

    @property
    def year(self) -> Series:
        out = []
        for x in self._s._data:
            if is_na(x):
                out.append(NAN)
            else:
                sx = str(x).strip()
                if len(sx) >= 4 and sx[:4].isdigit():
                    out.append(int(sx[:4]))
                else:
                    out.append(NAN)
        return Series(out)


class _Rolling:
    def __init__(self, s: Series, window: int, min_periods: int = 1):
        self._s = s
        self._w = max(1, int(window))
        self._mp = max(1, int(min_periods))

    def mean(self) -> Series:
        vals = [_to_float(x) for x in self._s._data]
        out = []
        for i in range(len(vals)):
            start = max(0, i - self._w + 1)
            chunk = [v for v in vals[start : i + 1] if not math.isnan(v)]
            if len(chunk) >= self._mp:
                out.append(sum(chunk) / len(chunk))
            else:
                out.append(NAN)
        return Series(out)


class Series:
    def __init__(self, data: Any = None, index: Iterable[int] | None = None):
        if isinstance(data, Series):
            self._data = list(data._data)
        elif isinstance(data, (list, tuple)):
            self._data = list(data)
        elif hasattr(data, "__iter__") and not isinstance(data, (str, bytes, dict)):
            self._data = list(data)
        else:
            if index is not None:
                idx_list = list(index)
                self._data = [data for _ in idx_list]
            else:
                self._data = [] if data is None else [data]

    @property
    def index(self) -> list[int]:
        return list(range(len(self._data)))

    @property
    def values(self) -> list[Any]:
        return self._data

    @property
    def empty(self) -> bool:
        return len(self._data) == 0

    def tolist(self) -> list[Any]:
        return list(self._data)

    def copy(self) -> Series:
        return Series(list(self._data))

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, Series):
            return Series([v for v, m in zip(self._data, key._data) if bool(m)])
        if isinstance(key, list) and key and isinstance(key[0], bool):
            return Series([v for v, m in zip(self._data, key) if bool(m)])
        if isinstance(key, slice):
            return Series(self._data[key])
        return self._data[key]

    @property
    def iloc(self):
        return _IlocList(self._data)

    @property
    def loc(self):
        return self

    def _binop(self, other: Any, op) -> Series:
        if isinstance(other, Series):
            return Series([op(a, b) for a, b in zip(self._data, other._data)])
        if isinstance(other, list):
            return Series([op(a, b) for a, b in zip(self._data, other)])
        return Series([op(a, other) for a in self._data])

    def __add__(self, other: Any) -> Series:
        def _add(a, b):
            if isinstance(a, str) or isinstance(b, str):
                return ("" if is_na(a) else str(a)) + ("" if is_na(b) else str(b))
            fa, fb = _to_float(a), _to_float(b)
            return NAN if (math.isnan(fa) or math.isnan(fb)) else (fa + fb)
        return self._binop(other, _add)

    def __radd__(self, other: Any) -> Series:
        def _radd(a, b):
            if isinstance(a, str) or isinstance(b, str):
                return ("" if is_na(b) else str(b)) + ("" if is_na(a) else str(a))
            fa, fb = _to_float(a), _to_float(b)
            return NAN if (math.isnan(fa) or math.isnan(fb)) else (fb + fa)
        return self._binop(other, _radd)

    def __sub__(self, other: Any) -> Series:
        def _sub(a, b):
            fa, fb = _to_float(a), _to_float(b)
            return NAN if (math.isnan(fa) or math.isnan(fb)) else (fa - fb)
        return self._binop(other, _sub)

    def __rsub__(self, other: Any) -> Series:
        def _rsub(a, b):
            fa, fb = _to_float(a), _to_float(b)
            return NAN if (math.isnan(fa) or math.isnan(fb)) else (fb - fa)
        return self._binop(other, _rsub)

    def __mul__(self, other: Any) -> Series:
        def _mul(a, b):
            fa, fb = _to_float(a), _to_float(b)
            return NAN if (math.isnan(fa) or math.isnan(fb)) else (fa * fb)
        return self._binop(other, _mul)

    def __rmul__(self, other: Any) -> Series:
        return self.__mul__(other)

    def __truediv__(self, other: Any) -> Series:
        def _div(a, b):
            fa, fb = _to_float(a), _to_float(b)
            if math.isnan(fa) or math.isnan(fb) or fb == 0.0:
                return NAN
            return fa / fb
        return self._binop(other, _div)

    def __rtruediv__(self, other: Any) -> Series:
        def _rdiv(a, b):
            fa, fb = _to_float(a), _to_float(b)
            if math.isnan(fa) or math.isnan(fb) or fa == 0.0:
                return NAN
            return fb / fa
        return self._binop(other, _rdiv)

    def __lt__(self, other: Any) -> Series:
        def _lt(a, b):
            if is_na(a) or is_na(b):
                return False
            fa, fb = _to_float(a), _to_float(b)
            if not (math.isnan(fa) or math.isnan(fb)):
                return fa < fb
            return str(a) < str(b)
        return self._binop(other, _lt)

    def __le__(self, other: Any) -> Series:
        def _le(a, b):
            if is_na(a) or is_na(b):
                return False
            fa, fb = _to_float(a), _to_float(b)
            if not (math.isnan(fa) or math.isnan(fb)):
                return fa <= fb
            return str(a) <= str(b)
        return self._binop(other, _le)

    def __gt__(self, other: Any) -> Series:
        def _gt(a, b):
            if is_na(a) or is_na(b):
                return False
            fa, fb = _to_float(a), _to_float(b)
            if not (math.isnan(fa) or math.isnan(fb)):
                return fa > fb
            return str(a) > str(b)
        return self._binop(other, _gt)

    def __ge__(self, other: Any) -> Series:
        def _ge(a, b):
            if is_na(a) or is_na(b):
                return False
            fa, fb = _to_float(a), _to_float(b)
            if not (math.isnan(fa) or math.isnan(fb)):
                return fa >= fb
            return str(a) >= str(b)
        return self._binop(other, _ge)

    def __eq__(self, other: Any) -> Series:  # type: ignore[override]
        return self.eq(other)

    def __ne__(self, other: Any) -> Series:  # type: ignore[override]
        return ~self.eq(other)

    def eq(self, other: Any) -> Series:
        def _eq(a, b):
            if is_na(a) or is_na(b):
                return False
            fa, fb = _to_float(a), _to_float(b)
            if not (math.isnan(fa) or math.isnan(fb)):
                return fa == fb
            return str(a) == str(b)
        return self._binop(other, _eq)

    def __and__(self, other: Any) -> Series:
        return self._binop(other, lambda a, b: bool(a) and bool(b))

    def __or__(self, other: Any) -> Series:
        return self._binop(other, lambda a, b: bool(a) or bool(b))

    def __invert__(self) -> Series:
        return Series([not bool(x) for x in self._data])

    def isna(self) -> Series:
        return Series([is_na(x) for x in self._data])

    def notna(self) -> Series:
        return Series([not_na(x) for x in self._data])

    def fillna(self, val: Any) -> Series:
        return Series([val if is_na(x) else x for x in self._data])

    def dropna(self) -> Series:
        return Series([x for x in self._data if not_na(x)])

    def replace(self, old: Any, new: Any) -> Series:
        out = []
        for x in self._data:
            if not is_na(x) and x == old:
                out.append(new)
            else:
                out.append(x)
        return Series(out)

    def astype(self, dtype: Any) -> Series:
        if dtype is str or dtype == "str" or dtype == "string":
            return Series(["" if is_na(x) else str(x) for x in self._data])
        if dtype is int or dtype == "int" or dtype == "Int64":
            out = []
            for x in self._data:
                fx = _to_float(x)
                out.append(0 if math.isnan(fx) else int(round(fx)))
            return Series(out)
        if dtype is float or dtype == "float":
            return Series([_to_float(x) for x in self._data])
        if dtype is bool or dtype == "bool":
            return Series([False if is_na(x) else bool(x) for x in self._data])
        return self.copy()

    def isin(self, values: Iterable[Any]) -> Series:
        vset = set(values)
        vstr = {str(v) for v in vset}
        return Series([(not is_na(x)) and (x in vset or str(x) in vstr) for x in self._data])

    def between(self, low: Any, high: Any) -> Series:
        return (self >= low) & (self <= high)

    def map(self, mapper: Any) -> Series:
        if callable(mapper):
            return Series([mapper(x) for x in self._data])
        return Series([mapper.get(x, NAN) for x in self._data])

    def sum(self) -> float:
        total = 0.0
        for x in self._data:
            if isinstance(x, bool):
                total += 1.0 if x else 0.0
            else:
                fx = _to_float(x)
                if not math.isnan(fx):
                    total += fx
        return total

    def mean(self) -> float:
        vals = []
        for x in self._data:
            if isinstance(x, bool):
                vals.append(1.0 if x else 0.0)
            else:
                fx = _to_float(x)
                if not math.isnan(fx):
                    vals.append(fx)
        return (sum(vals) / len(vals)) if vals else NAN

    def min(self) -> Any:
        vals = [x for x in self._data if not_na(x)]
        return min(vals) if vals else NAN

    def max(self) -> Any:
        vals = [x for x in self._data if not_na(x)]
        return max(vals) if vals else NAN

    def unique(self) -> list[Any]:
        seen = []
        seen_set = set()
        for x in self._data:
            if is_na(x):
                continue
            if x not in seen_set:
                seen_set.add(x)
                seen.append(x)
        return seen

    def nunique(self) -> int:
        return len(self.unique())

    def cumsum(self) -> Series:
        out = []
        acc = 0.0
        for x in self._data:
            fx = _to_float(x)
            if not math.isnan(fx):
                acc += fx
            out.append(acc)
        return Series(out)

    def rolling(self, window: int, min_periods: int = 1) -> _Rolling:
        return _Rolling(self, window, min_periods=min_periods)

    @property
    def str(self) -> _StrAccessor:
        return _StrAccessor(self)

    @property
    def dt(self) -> _DtAccessor:
        return _DtAccessor(self)


class _GroupBySeries:
    def __init__(self, gb: _GroupBy, col: str):
        self._gb = gb
        self._col = col

    def sum(self) -> DataFrame:
        return self._gb.agg(**{self._col: (self._col, "sum")})

    def cumsum(self) -> Series:
        rows = self._gb._df._rows
        keys = self._gb._by
        acc: dict[tuple[Any, ...], float] = defaultdict(float)
        out = []
        for r in rows:
            k = tuple(r.get(c) for c in keys)
            fv = _to_float(r.get(self._col))
            if not math.isnan(fv):
                acc[k] += fv
            out.append(acc[k])
        return Series(out)


class _GroupBy:
    def __init__(self, df: DataFrame, by: str | list[str], as_index: bool = False, sort: bool = True):
        self._df = df
        self._by = [by] if isinstance(by, str) else list(by)
        self._as_index = as_index
        self._sort = sort

    def __getitem__(self, col: str) -> _GroupBySeries:
        return _GroupBySeries(self, col)

    def __getattr__(self, col: str) -> _GroupBySeries:
        if col in self._df.columns:
            return _GroupBySeries(self, col)
        raise AttributeError(col)

    def __iter__(self):
        groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        single = len(self._by) == 1
        for r in self._df._rows:
            k = r.get(self._by[0]) if single else tuple(r.get(c) for c in self._by)
            groups[k].append(r)
        keys = list(groups.keys())
        if self._sort:
            try:
                keys.sort()
            except TypeError:
                pass
        for k in keys:
            yield k, DataFrame(groups[k], columns=self._df.columns)

    def agg(self, **named_aggs: tuple[str, Any]) -> DataFrame:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in self._df._rows:
            k = tuple(r.get(c) for c in self._by)
            groups[k].append(r)
        out_rows = []
        for k, grp in groups.items():
            row_dict: dict[str, Any] = {}
            for c, kv in zip(self._by, k):
                row_dict[c] = kv
            for out_col, (src_col, func) in named_aggs.items():
                if func == "size" or func == "count":
                    row_dict[out_col] = len(grp)
                elif func == "sum":
                    s = 0.0
                    for r in grp:
                        v = r.get(src_col)
                        if isinstance(v, bool):
                            s += 1.0 if v else 0.0
                        else:
                            fv = _to_float(v)
                            if not math.isnan(fv):
                                s += fv
                    row_dict[out_col] = s
                elif func == "mean":
                    vals = [_to_float(r.get(src_col)) for r in grp]
                    vals = [v for v in vals if not math.isnan(v)]
                    row_dict[out_col] = (sum(vals) / len(vals)) if vals else NAN
                elif callable(func):
                    row_dict[out_col] = func(Series([r.get(src_col) for r in grp]))
            out_rows.append(row_dict)
        cols = list(self._by) + list(named_aggs.keys())
        return DataFrame(out_rows, columns=cols)


class _LocIndexer:
    def __init__(self, df: DataFrame):
        self._df = df

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, tuple) and len(key) == 2:
            row_sel, col_sel = key
            sub = self._df[row_sel]
            return sub[col_sel]
        return self._df[key]


class _IlocIndexer:
    def __init__(self, df: DataFrame):
        self._df = df

    def __getitem__(self, idx: int) -> Row:
        return Row(self._df._rows[idx])


class DataFrame:
    def __init__(self, data: Any = None, columns: list[str] | None = None):
        if isinstance(data, DataFrame):
            self._rows = [dict(r) for r in data._rows]
            self._cols = list(data._cols)
        elif isinstance(data, list):
            self._rows = [dict(r) for r in data]
            if columns is not None:
                self._cols = list(columns)
            elif self._rows:
                self._cols = list(self._rows[0].keys())
            else:
                self._cols = []
        elif isinstance(data, dict):
            cols = list(data.keys())
            col_lists = {c: (list(v._data) if isinstance(v, Series) else list(v)) for c, v in data.items()}
            n = len(next(iter(col_lists.values()))) if col_lists else 0
            self._rows = [{c: col_lists[c][i] for c in cols} for i in range(n)]
            self._cols = cols
        else:
            self._rows = []
            self._cols = list(columns) if columns else []

    @property
    def columns(self) -> list[str]:
        return list(self._cols)

    @property
    def empty(self) -> bool:
        return len(self._rows) == 0

    @property
    def index(self) -> list[int]:
        return list(range(len(self._rows)))

    def __len__(self) -> int:
        return len(self._rows)

    def copy(self) -> DataFrame:
        return DataFrame([dict(r) for r in self._rows], columns=list(self._cols))

    def get(self, col: str, default: Any = None) -> Any:
        if col in self._cols:
            return self[col]
        return default

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return Series([r.get(key, NAN) for r in self._rows])
        if isinstance(key, list):
            if key and isinstance(key[0], bool):
                return DataFrame([dict(r) for r, m in zip(self._rows, key) if bool(m)], columns=list(self._cols))
            cols = [c for c in key]
            return DataFrame([{c: r.get(c, NAN) for c in cols} for r in self._rows], columns=cols)
        if isinstance(key, Series):
            return DataFrame([dict(r) for r, m in zip(self._rows, key._data) if bool(m)], columns=list(self._cols))
        raise KeyError(str(key))

    def __setitem__(self, col: str, val: Any) -> None:
        if col not in self._cols:
            self._cols.append(col)
        if isinstance(val, Series):
            for r, v in zip(self._rows, val._data):
                r[col] = v
        elif isinstance(val, (list, tuple, range)):
            for r, v in zip(self._rows, val):
                r[col] = v
        else:
            for r in self._rows:
                r[col] = val

    def __getattr__(self, name: str) -> Any:
        if "_cols" in self.__dict__ and name in self._cols:
            return self[name]
        raise AttributeError(name)

    @property
    def iloc(self) -> _IlocIndexer:
        return _IlocIndexer(self)

    @property
    def loc(self) -> _LocIndexer:
        return _LocIndexer(self)

    def iterrows(self):
        for i, r in enumerate(self._rows):
            yield i, Row(r)

    def head(self, n: int = 5) -> DataFrame:
        return DataFrame([dict(r) for r in self._rows[:n]], columns=list(self._cols))

    def tail(self, n: int = 5) -> DataFrame:
        if n <= 0:
            return DataFrame([], columns=list(self._cols))
        return DataFrame([dict(r) for r in self._rows[-n:]], columns=list(self._cols))

    def assign(self, **kwargs: Any) -> DataFrame:
        out = self.copy()
        for k, v in kwargs.items():
            out[k] = v(out) if callable(v) else v
        return out

    def rename(self, columns: dict[str, str] | None = None) -> DataFrame:
        if not columns:
            return self.copy()
        new_cols = [columns.get(c, c) for c in self._cols]
        new_rows = [{columns.get(k, k): v for k, v in r.items()} for r in self._rows]
        return DataFrame(new_rows, columns=new_cols)

    def reset_index(self, drop: bool = True) -> DataFrame:
        return self.copy()

    def drop_duplicates(self, subset: str | list[str] | None = None) -> DataFrame:
        cols = [subset] if isinstance(subset, str) else (list(subset) if subset else list(self._cols))
        seen = set()
        out = []
        for r in self._rows:
            k = tuple(r.get(c) for c in cols)
            if k not in seen:
                seen.add(k)
                out.append(dict(r))
        return DataFrame(out, columns=list(self._cols))

    def dropna(self, subset: list[str] | None = None) -> DataFrame:
        cols = list(subset) if subset else list(self._cols)
        out = [dict(r) for r in self._rows if all(not_na(r.get(c)) for c in cols)]
        return DataFrame(out, columns=list(self._cols))

    def sort_values(
        self,
        by: str | list[str],
        ascending: bool | list[bool] = True,
        na_position: str = "last",
    ) -> DataFrame:
        cols = [by] if isinstance(by, str) else list(by)
        asc_list = [ascending] * len(cols) if isinstance(ascending, bool) else list(ascending)
        rows = [dict(r) for r in self._rows]

        for col, asc in reversed(list(zip(cols, asc_list))):
            non_na = [r for r in rows if not_na(r.get(col))]
            na_rows = [r for r in rows if is_na(r.get(col))]

            def _sort_key(r):
                v = r.get(col)
                fv = _to_float(v)
                if not math.isnan(fv):
                    return (0, fv, "")
                return (1, 0.0, str(v))

            non_na.sort(key=_sort_key, reverse=not asc)
            rows = (na_rows + non_na) if na_position == "first" else (non_na + na_rows)

        return DataFrame(rows, columns=list(self._cols))

    def groupby(self, by: str | list[str], as_index: bool = False, sort: bool = True) -> _GroupBy:
        return _GroupBy(self, by, as_index=as_index, sort=sort)

    def merge(
        self,
        right: DataFrame,
        on: str | list[str],
        how: str = "left",
        suffixes: tuple[str, str] = ("_x", "_y"),
    ) -> DataFrame:
        keys = [on] if isinstance(on, str) else list(on)
        r_index: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for rr in right._rows:
            k = tuple(str(rr.get(c)) for c in keys)
            r_index[k].append(rr)

        left_only = [c for c in self._cols if c not in keys]
        right_only = [c for c in right._cols if c not in keys]
        overlap = set(left_only) & set(right_only)

        out_cols = []
        for c in self._cols:
            out_cols.append(f"{c}{suffixes[0]}" if c in overlap else c)
        for c in right_only:
            out_cols.append(f"{c}{suffixes[1]}" if c in overlap else c)

        out_rows = []
        for lr in self._rows:
            k = tuple(str(lr.get(c)) for c in keys)
            matches = r_index.get(k)
            if matches:
                for rr in matches:
                    merged: dict[str, Any] = {}
                    for c in self._cols:
                        mc = f"{c}{suffixes[0]}" if c in overlap else c
                        merged[mc] = lr.get(c)
                    for c in right_only:
                        mc = f"{c}{suffixes[1]}" if c in overlap else c
                        merged[mc] = rr.get(c)
                    out_rows.append(merged)
            elif how == "left":
                merged = {}
                for c in self._cols:
                    mc = f"{c}{suffixes[0]}" if c in overlap else c
                    merged[mc] = lr.get(c)
                for c in right_only:
                    mc = f"{c}{suffixes[1]}" if c in overlap else c
                    merged[mc] = NAN
                out_rows.append(merged)
        return DataFrame(out_rows, columns=out_cols)

    def melt(
        self,
        id_vars: str | list[str],
        value_vars: list[str],
        var_name: str = "variable",
        value_name: str = "value",
    ) -> DataFrame:
        ids = [id_vars] if isinstance(id_vars, str) else list(id_vars)
        out_cols = ids + [var_name, value_name]
        out_rows = []
        for r in self._rows:
            for vv in value_vars:
                nr = {c: r.get(c) for c in ids}
                nr[var_name] = vv
                nr[value_name] = r.get(vv, NAN)
                out_rows.append(nr)
        return DataFrame(out_rows, columns=out_cols)

    def to_csv(self, path: str | Path, index: bool = False) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self._cols)
            w.writeheader()
            for r in self._rows:
                clean = {k: ("" if is_na(v) else v) for k, v in r.items() if k in self._cols}
                w.writerow(clean)


# ----------------------------------------------------------------------------
# NumPy & Pandas drop-in namespaces
# ----------------------------------------------------------------------------
class _NumPyNamespace:
    nan = NAN

    @staticmethod
    def where(cond: Any, x: Any, y: Any) -> Series:
        c_list = cond._data if isinstance(cond, Series) else list(cond)
        n = len(c_list)
        x_list = x._data if isinstance(x, Series) else (x if isinstance(x, list) else [x] * n)
        y_list = y._data if isinstance(y, Series) else (y if isinstance(y, list) else [y] * n)
        return Series([xv if bool(cv) else yv for cv, xv, yv in zip(c_list, x_list, y_list)])

    @staticmethod
    def isclose(a: float, b: float, rel_tol: float = 1e-9, abs_tol: float = 1e-6) -> bool:
        return math.isclose(_to_float(a), _to_float(b), rel_tol=rel_tol, abs_tol=abs_tol)


class _PandasNamespace:
    DataFrame = DataFrame
    Series = Series

    @staticmethod
    def isna(v: Any) -> Any:
        if isinstance(v, Series):
            return v.isna()
        return is_na(v)

    @staticmethod
    def notna(v: Any) -> Any:
        if isinstance(v, Series):
            return v.notna()
        return not_na(v)

    @staticmethod
    def read_csv(path: str | Path, low_memory: bool = False) -> DataFrame:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_cols = list(reader.fieldnames or [])
            cols = [c.lstrip("\ufeff").strip() for c in raw_cols]
            col_map = dict(zip(raw_cols, cols))
            rows = []
            for raw_row in reader:
                rows.append({col_map.get(k, k): _try_num(v) for k, v in raw_row.items() if k is not None})
        return DataFrame(rows, columns=cols)

    @staticmethod
    def to_numeric(s: Any, errors: str = "coerce") -> Series:
        items = s._data if isinstance(s, Series) else list(s)
        return Series([_to_float(x) for x in items])

    @staticmethod
    def to_datetime(s: Any, errors: str = "coerce", dayfirst: bool = True) -> Series:
        items = s._data if isinstance(s, Series) else list(s)
        out = []
        for x in items:
            if is_na(x):
                out.append("")
                continue
            sx = str(x).strip()
            if len(sx) >= 10 and sx[4:5] == "-" and sx[7:8] == "-":
                out.append(sx[:10])
                continue
            parsed = ""
            for fmt_str in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y"):
                try:
                    parsed = datetime.strptime(sx[:11].strip(), fmt_str).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            out.append(parsed or sx)
        return Series(out)

    @staticmethod
    def concat(dfs: Iterable[DataFrame]) -> DataFrame:
        df_list = list(dfs)
        if not df_list:
            return DataFrame()
        cols = list(df_list[0].columns)
        rows = []
        for d in df_list:
            for c in d.columns:
                if c not in cols:
                    cols.append(c)
            rows.extend([dict(r) for r in d._rows])
        return DataFrame(rows, columns=cols)


# ----------------------------------------------------------------------------
# Plotly Express (px) drop-in built on plotly.graph_objects
# ----------------------------------------------------------------------------
def _extract_customdata(df: DataFrame, custom_data: list[str] | None) -> list[list[Any]] | None:
    if not custom_data:
        return None
    cols = [df[c].tolist() for c in custom_data]
    return [list(row_vals) for row_vals in zip(*cols)] if cols else None


class _PlotlyExpressNamespace:
    @staticmethod
    def bar(
        df: DataFrame,
        x: str,
        y: str,
        orientation: str = "v",
        color: str | Series | Any = None,
        barmode: str = "relative",
        color_continuous_scale: list[str] | None = None,
        color_discrete_map: dict[str, str] | None = None,
        color_discrete_sequence: list[str] | None = None,
        text: str | None = None,
        text_auto: str | bool | None = None,
        custom_data: list[str] | None = None,
        category_orders: dict[str, list[Any]] | None = None,
        labels: dict[str, str] | None = None,
    ) -> go.Figure:
        labels = labels or {}
        fig = go.Figure()

        # Check if color is categorical (discrete) vs continuous numeric
        is_discrete = False
        color_vals: list[Any] = []
        if color is not None:
            if isinstance(color, str) and color in df.columns:
                color_vals = df[color].tolist()
            elif isinstance(color, Series):
                color_vals = color.tolist()
            elif hasattr(color, "__iter__") and not isinstance(color, (str, bytes)):
                color_vals = list(color)
            if color_discrete_map is not None or any(isinstance(v, str) for v in color_vals if not_na(v)):
                is_discrete = True

        if is_discrete and color_vals:
            df_work = df.copy()
            col_key = color if isinstance(color, str) and color in df.columns else "_px_color"
            if col_key == "_px_color":
                df_work[col_key] = color_vals
            cats = []
            for v in df_work[col_key].tolist():
                if not_na(v) and v not in cats:
                    cats.append(v)
            seq = color_discrete_sequence or ["#0f766e", "#d97706", "#0284c7", "#7c3aed", "#db2777"]
            for idx, cat in enumerate(cats):
                sub = df_work[df_work[col_key] == cat]
                c_hex = (color_discrete_map or {}).get(cat, seq[idx % len(seq)])
                cdata = _extract_customdata(sub, custom_data)
                txt = sub[text].tolist() if (text and text in sub.columns) else None
                fig.add_trace(
                    go.Bar(
                        name=str(cat),
                        x=sub[x].tolist(),
                        y=sub[y].tolist(),
                        orientation=orientation,
                        marker_color=c_hex,
                        text=txt,
                        customdata=cdata,
                    )
                )
            fig.update_layout(barmode=barmode)
        else:
            cdata = _extract_customdata(df, custom_data)
            txt = None
            if text and text in df.columns:
                txt = df[text].tolist()
            elif text_auto:
                target_col = y if orientation == "v" else x
                fmt_spec = text_auto if isinstance(text_auto, str) else ".1f"
                txt = [f"{_to_float(v):{fmt_spec}}" if not_na(v) else "" for v in df[target_col].tolist()]

            marker_dict: dict[str, Any] = {}
            if color_vals:
                marker_dict["color"] = [_to_float(v) for v in color_vals]
                marker_dict["coloraxis"] = "coloraxis"
            trace_kwargs: dict[str, Any] = dict(
                x=df[x].tolist(),
                y=df[y].tolist(),
                orientation=orientation,
                text=txt,
                customdata=cdata,
            )
            if marker_dict:
                trace_kwargs["marker"] = marker_dict
            fig.add_trace(go.Bar(**trace_kwargs))
            if color_continuous_scale:
                fig.update_layout(coloraxis=dict(colorscale=color_continuous_scale))

        if category_orders:
            for ax_col, order_list in category_orders.items():
                if ax_col == y:
                    fig.update_yaxes(categoryorder="array", categoryarray=order_list)
                elif ax_col == x:
                    fig.update_xaxes(categoryorder="array", categoryarray=order_list)

        fig.update_layout(
            xaxis_title=labels.get(x, x),
            yaxis_title=labels.get(y, y),
        )
        return fig

    @staticmethod
    def line(
        df: DataFrame,
        x: str,
        y: str,
        color: str | None = None,
        markers: bool = False,
        color_discrete_sequence: list[str] | None = None,
        custom_data: list[str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> go.Figure:
        labels = labels or {}
        fig = go.Figure()
        mode = "lines+markers" if markers else "lines"
        seq = color_discrete_sequence or ["#0f766e", "#d97706", "#2563eb", "#7c3aed"]

        if color and color in df.columns:
            cats = df[color].unique()
            for idx, cat in enumerate(cats):
                sub = df[df[color] == cat]
                cdata = _extract_customdata(sub, custom_data)
                fig.add_trace(
                    go.Scatter(
                        name=str(cat),
                        x=sub[x].tolist(),
                        y=sub[y].tolist(),
                        mode=mode,
                        line=dict(color=seq[idx % len(seq)], width=3),
                        customdata=cdata,
                    )
                )
        else:
            cdata = _extract_customdata(df, custom_data)
            fig.add_trace(
                go.Scatter(
                    x=df[x].tolist(),
                    y=df[y].tolist(),
                    mode=mode,
                    line=dict(color=seq[0], width=3),
                    customdata=cdata,
                )
            )
        fig.update_layout(
            xaxis_title=labels.get(x, x),
            yaxis_title=labels.get(y, y),
        )
        return fig

    @staticmethod
    def scatter(
        df: DataFrame,
        x: str,
        y: str,
        size: str | None = None,
        color: str | None = None,
        text: str | None = None,
        hover_name: str | None = None,
        size_max: int = 24,
        color_continuous_scale: list[str] | None = None,
        color_discrete_map: dict[str, str] | None = None,
        custom_data: list[str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> go.Figure:
        labels = labels or {}
        fig = go.Figure()

        def _compute_sizes(sub_df: DataFrame, max_val_global: float) -> list[float] | int:
            if not size or size not in sub_df.columns or max_val_global <= 0:
                return 10
            out_s = []
            for v in sub_df[size].tolist():
                fv = _to_float(v)
                if math.isnan(fv) or fv <= 0:
                    out_s.append(7.0)
                else:
                    out_s.append(max(7.0, size_max * math.sqrt(fv / max_val_global)))
            return out_s

        max_size_val = _to_float(df[size].max()) if (size and size in df.columns and not df.empty) else 1.0
        is_discrete = False
        if color and color in df.columns:
            c_vals = df[color].tolist()
            if color_discrete_map is not None or any(isinstance(v, str) for v in c_vals if not_na(v)):
                is_discrete = True

        mode = "markers+text" if (text and text in df.columns) else "markers"

        if is_discrete and color:
            cats = df[color].unique()
            seq = ["#0f766e", "#d97706", "#0284c7", "#64748b", "#94a3b8", "#7c3aed"]
            for idx, cat in enumerate(cats):
                sub = df[df[color] == cat]
                cdata = _extract_customdata(sub, custom_data)
                htext = sub[hover_name].tolist() if (hover_name and hover_name in sub.columns) else None
                txt = sub[text].tolist() if (text and text in sub.columns) else None
                c_hex = (color_discrete_map or {}).get(cat, seq[idx % len(seq)])
                fig.add_trace(
                    go.Scatter(
                        name=str(cat),
                        x=sub[x].tolist(),
                        y=sub[y].tolist(),
                        mode=mode,
                        text=txt,
                        hovertext=htext,
                        customdata=cdata,
                        marker=dict(color=c_hex, size=_compute_sizes(sub, max_size_val)),
                    )
                )
        else:
            cdata = _extract_customdata(df, custom_data)
            htext = df[hover_name].tolist() if (hover_name and hover_name in df.columns) else None
            txt = df[text].tolist() if (text and text in df.columns) else None
            marker_cfg: dict[str, Any] = dict(size=_compute_sizes(df, max_size_val))
            if color and color in df.columns:
                marker_cfg["color"] = [_to_float(v) for v in df[color].tolist()]
                marker_cfg["coloraxis"] = "coloraxis"
            fig.add_trace(
                go.Scatter(
                    x=df[x].tolist(),
                    y=df[y].tolist(),
                    mode=mode,
                    text=txt,
                    hovertext=htext,
                    customdata=cdata,
                    marker=marker_cfg,
                )
            )
            if color_continuous_scale:
                cbar_title = labels.get(color, color) if color else ""
                fig.update_layout(coloraxis=dict(colorscale=color_continuous_scale, colorbar=dict(title=cbar_title)))

        fig.update_layout(
            xaxis_title=labels.get(x, x),
            yaxis_title=labels.get(y, y),
        )
        return fig

    @staticmethod
    def pie(
        df: DataFrame,
        names: str,
        values: str,
        hole: float = 0.0,
        color_discrete_sequence: list[str] | None = None,
    ) -> go.Figure:
        fig = go.Figure(
            go.Pie(
                labels=df[names].tolist(),
                values=df[values].tolist(),
                hole=hole,
                marker=dict(colors=color_discrete_sequence) if color_discrete_sequence else None,
            )
        )
        return fig

    @staticmethod
    def histogram(
        df: DataFrame,
        x: str,
        nbins: int = 20,
        labels: dict[str, str] | None = None,
    ) -> go.Figure:
        labels = labels or {}
        fig = go.Figure(
            go.Histogram(
                x=df[x].tolist(),
                nbinsx=nbins,
            )
        )
        fig.update_layout(
            xaxis_title=labels.get(x, x),
            yaxis_title="Count",
        )
        return fig


np = _NumPyNamespace()
pd = _PandasNamespace()
px = _PlotlyExpressNamespace()

# Allow Plotly validators (go.Bar, go.Scatter, fig.add_bar, etc.) to accept Series and DataFrame directly
try:
    from _plotly_utils.basevalidators import DataArrayValidator

    _orig_validate_coerce = DataArrayValidator.validate_coerce

    def _patched_validate_coerce(self, v):
        if isinstance(v, Series):
            v = [None if (isinstance(x, float) and math.isnan(x)) else x for x in v._data]
        elif isinstance(v, DataFrame):
            v = [
                [None if (isinstance( r.get(c), float) and math.isnan(r.get(c))) else r.get(c) for c in v._cols]
                for r in v._rows
            ]
        return _orig_validate_coerce(self, v)

    DataArrayValidator.validate_coerce = _patched_validate_coerce
except Exception:
    pass

