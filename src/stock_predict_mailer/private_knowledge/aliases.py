"""Reviewable spelling table for query expansion; no model, no per-corpus tuning.

Retrieval here is literal: a chunk is reachable when its own wording overlaps the
query. Readers type 三季报 while a filing writes 第三季度报告, and 营收 while a
spreadsheet writes 营业收入, so "the answer is in the corpus but not in the
results" is usually a vocabulary gap rather than a broken index.

Two properties are deliberate:

* **Query side only.** The index keeps whatever the source document said, so an
  expansion can never invent evidence, and adding a spelling here needs no
  re-import. ``expand()`` returns the rewritten query plus the pairs that fired,
  and the caller echoes them: an operator must be able to see why a document
  surfaced.
* **One-way.** Each group names its canonical spelling first. 营收 pulls in
  营业收入; 营业收入 pulls in nothing, because expanding a query that is already
  written the way the corpus writes it only adds noise to the ranking.
* **Spelling variants only.** Neighbouring concepts stay out. 产能利用率 and 开工率
  are different measurements, 降准 and 降息 are different policies; mapping either
  pair would confidently answer a question nobody asked. A wrong mapping is worse
  than a missing one, because a miss is visible and a wrong hit is not.

The table is a code constant rather than configuration: it is small, it is read
by everyone who tunes retrieval, and a diff is the review that keeps it honest.
"""
from __future__ import annotations

import re

# Interchangeable spellings of one concept; **the first member is the canonical
# one**. Expansion is one-way — a query that already uses the canonical wording is
# left untouched, only shorthand and abbreviations pull in their siblings.
GROUPS = (
    # 报告期：标题写法、口语缩写与季度编号
    ("第三季度报告", "三季报", "三季度报告", "Q3", "3Q"),
    ("第一季度报告", "一季报", "一季度报告", "Q1", "1Q"),
    ("半年度报告", "半年报", "中报", "H1"),
    ("年度报告", "年报"),
    ("季度报告", "季报"),
    ("第三季度", "三季度"),
    ("半年度", "上半年"),
    # 财务指标：报表行名与口语缩写
    ("营业收入", "营收"),
    ("净利润", "净利"),
    ("归属于母公司股东的净利润", "归母净利", "归母净利润"),
    ("扣除非经常性损益", "扣非"),
    ("基本每股收益", "每股收益", "EPS"),
    ("净资产收益率", "ROE", "加权平均净资产收益率"),
    ("不良贷款率", "不良率"),
    ("拨备覆盖率", "拨备"),
    ("资产总额", "总资产"),
    # 宏观：指标缩写与统计口径全称
    ("居民消费价格指数", "CPI"),
    ("工业生产者出厂价格指数", "PPI"),
    ("国内生产总值", "GDP"),
    ("社会融资规模", "社融"),
    ("社会消费品零售总额", "社零"),
    ("固定资产投资", "固投"),
    ("广义货币供应量", "M2"),
    ("贷款市场报价利率", "LPR"),
    ("公开市场操作", "OMO"),
    ("存款准备金率", "降准", "下调存款准备金率"),
    # 产业链与行情
    ("供应商", "供货商"),
    ("头部厂商", "龙头", "头部企业"),
    ("价格上行", "涨价", "提价"),
    ("价格下行", "降价", "跌价"),
)

ALIASES = {member: tuple(other for other in group if other != member)
           for group in GROUPS for member in group[1:]}
# 长的先匹配：「三季报」必须在「季报」之前吃掉这三个字，否则「季报」会把
# 「三季度报告」当成口语而重复扩展。
ORDER = sorted(ALIASES, key=len, reverse=True)


def expand(query):
    """Return ``(expanded query, applied pairs)``; the query itself when nothing fires.

    Matching is case-insensitive so ``cpi`` finds ``CPI``, and overlapping matches
    are claimed left to right by the longest alias, so ``三季报`` never also fires
    ``季报``. Additions are appended as plain text: downstream only tokenises them,
    and keeping the original query intact keeps the echo honest.
    """
    lowered, taken, seen, additions, applied = query.casefold(), [False] * len(query), set(), [], []
    for alias in ORDER:
        for found in re.finditer(re.escape(alias), query, re.IGNORECASE):
            start, end = found.start(), found.end()
            if any(taken[position] for position in range(start, end)):
                continue
            taken[start:end] = [True] * (end - start)
            extra = [word for word in ALIASES[alias]
                     if word.casefold() not in lowered and word.casefold() not in seen]
            if extra:
                seen.update(word.casefold() for word in extra)
                additions.extend(extra)
                applied.append({"alias": alias, "canonical": extra})
    return (" ".join([query, *additions]) if additions else query), applied
