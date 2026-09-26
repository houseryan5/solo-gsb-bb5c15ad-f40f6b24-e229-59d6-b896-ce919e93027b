"""骑马钉（saddle-stitched）小册子拼版核心算法。

规则概述
--------
1. 每张纸正反两面各印 2 页，对折后 1 张纸 = 4 个版面，因此每册页数必须
   补齐到 4 的倍数，补位页为空白页。
2. 原稿按顺序分册：除最后一册外，每册都装满 ``4 * max_sheets_per_booklet`` 页。
3. 对一册已补齐到 ``n`` 页（``n`` 为 4 的倍数）的小册子，纸张从外到内编号
   为 ``i = 0 .. n/4-1``，每张纸：

   - 正面（front，朝外的一面）：左页 ``n - 2i``，右页 ``1 + 2i``
   - 反面（back，朝内的一面）：左页 ``2 + 2i``，右页 ``n - 1 - 2i``

   按此拼版双面打印（沿短边翻转）并对折后，翻开顺序即为 1, 2, 3, ..., n。
4. 补齐的空白页编号为 0，对外用 ``None``（JSON null）表示。

除按总页数连续分册（``build_imposition``）外，本模块还支持按章节分册
（``build_chapter_imposition``）：章节不可拆分、仅相邻章节可合册，
在所有合法分册中依次最小化总纸张数、册数，并以分册结束章节序号序列的
字典序裁决并列。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class BookletRange:
    """一册对应的原稿区间（页码均为 1-based，闭区间）。"""

    index: int
    start_page: int
    end_page: int
    padded_pages: int

    @property
    def original_pages(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def sheet_count(self) -> int:
        return self.padded_pages // 4

    @property
    def blank_pages(self) -> int:
        return self.padded_pages - self.original_pages


@dataclass(frozen=True)
class ChapterBookletRange:
    """按章节分册的一册（章节序号与原稿页码均为 1-based 闭区间）。"""

    index: int
    start_chapter: int
    end_chapter: int
    start_page: int
    end_page: int
    padded_pages: int

    @property
    def original_pages(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def sheet_count(self) -> int:
        return self.padded_pages // 4

    @property
    def blank_pages(self) -> int:
        return self.padded_pages - self.original_pages


def _ceil_to_multiple_of_four(value: int) -> int:
    return ((value + 3) // 4) * 4


def split_booklets(total_pages: int, max_sheets_per_booklet: int) -> list[BookletRange]:
    """把连续原稿页分册，并返回每册补齐到 4 的倍数后的页数。

    分册时先装满前面各册（每册 ``4 * max_sheets_per_booklet`` 页），
    剩余页归入最后一册，仅最后一册可能需要补空白页。
    """
    capacity = 4 * max_sheets_per_booklet
    booklets: list[BookletRange] = []
    start = 1
    index = 0
    while start <= total_pages:
        end = min(total_pages, start + capacity - 1)
        original = end - start + 1
        booklets.append(
            BookletRange(
                index=index,
                start_page=start,
                end_page=end,
                padded_pages=_ceil_to_multiple_of_four(original),
            )
        )
        start = end + 1
        index += 1
    return booklets


def impose_padded_booklet(padded_pages: int) -> list[dict[str, dict[str, int]]]:
    """对一册已补齐到 4 的倍数的版面做拼版。

    返回纸张列表（从外到内），每张纸为
    ``{"front": {"left": ..., "right": ...}, "back": {...}}``，
    页码为该册补齐版面上的 1-based 编号，空白页用 0 表示。
    """
    if padded_pages <= 0 or padded_pages % 4 != 0:
        raise ValueError("padded_pages 必须是正的 4 的倍数")

    n = padded_pages
    sheets: list[dict[str, dict[str, int]]] = []
    for i in range(n // 4):
        sheets.append(
            {
                "front": {"left": n - 2 * i, "right": 1 + 2 * i},
                "back": {"left": 2 + 2 * i, "right": n - 1 - 2 * i},
            }
        )
    return sheets


def _to_original(position: int, booklet: BookletRange | ChapterBookletRange) -> int | None:
    """把补齐版面位置（1-based）映射为原稿页码。

    补白页统一追加在原稿之后，因此位置大于本册原稿页数的版面即为空白页。
    """
    if position > booklet.original_pages:
        return None
    return booklet.start_page + position - 1


def _impose_booklet_sheets(
    booklet: BookletRange | ChapterBookletRange,
) -> list[dict]:
    """对一册做拼版：纸张从外到内，给出正反面左右的原稿页码（补白为 None）。"""
    layout = impose_padded_booklet(booklet.padded_pages)
    return [
        {
            "index": i,
            "front": {
                "left": _to_original(sheet["front"]["left"], booklet),
                "right": _to_original(sheet["front"]["right"], booklet),
            },
            "back": {
                "left": _to_original(sheet["back"]["left"], booklet),
                "right": _to_original(sheet["back"]["right"], booklet),
            },
        }
        for i, sheet in enumerate(layout)
    ]


def build_imposition(total_pages: int, max_sheets_per_booklet: int) -> dict:
    """完整拼版：分册 -> 补齐 -> 每册从外到内给出正反面左右页码。"""
    booklets = split_booklets(total_pages, max_sheets_per_booklet)
    result_booklets: list[dict] = []

    for booklet in booklets:
        result_booklets.append(
            {
                "index": booklet.index,
                "start_page": booklet.start_page,
                "end_page": booklet.end_page,
                "original_pages": booklet.original_pages,
                "padded_pages": booklet.padded_pages,
                "blank_pages": booklet.blank_pages,
                "sheet_count": booklet.sheet_count,
                "sheets": _impose_booklet_sheets(booklet),
            }
        )

    return {
        "total_pages": total_pages,
        "max_sheets_per_booklet": max_sheets_per_booklet,
        "booklet_count": len(booklets),
        "total_sheets": sum(b.sheet_count for b in booklets),
        "booklets": result_booklets,
    }


def split_chapter_booklets(
    chapter_pages: list[int], max_sheets_per_booklet: int
) -> list[ChapterBookletRange]:
    """按“章节不可拆分、仅相邻章节可合册”的约束求最优分册。

    合法分册须满足每册页数不超过 ``4 * max_sheets_per_booklet``。在所有合法
    分册中依次最小化：

    1. 总纸张数（每册页数先补齐到 4 的倍数，再除以 4 得到该册纸张数）；
    2. 分册数；
    3. 分册结束章节序号序列的字典序（取最小者）。

    用动态规划求解：``best[i]`` 表示前 ``i`` 章的最优
    ``(总纸张数, 册数, 结束章节序号元组)``，目标按元组字典序比较，
    与上述优先级一一对应。
    """
    capacity = 4 * max_sheets_per_booklet
    for pages in chapter_pages:
        if pages > capacity:
            raise ValueError(
                f"单章 {pages} 页超过每册容量上限 {capacity} 页，章节不可拆分"
            )

    n = len(chapter_pages)
    best: list[tuple[int, int, tuple[int, ...]] | None] = [None] * (n + 1)
    best[0] = (0, 0, ())
    for i in range(1, n + 1):
        group_pages = 0
        # 末册为第 j+1..i 章（1-based），从后往前累加，超容量即停止。
        for j in range(i - 1, -1, -1):
            group_pages += chapter_pages[j]
            if group_pages > capacity:
                break
            prev = best[j]
            if prev is None:
                continue
            candidate = (
                prev[0] + _ceil_to_multiple_of_four(group_pages) // 4,
                prev[1] + 1,
                prev[2] + (i,),
            )
            if best[i] is None or candidate < best[i]:
                best[i] = candidate

    # 每章均可单独成册，best[n] 必然有解。
    assert best[n] is not None
    _, _, end_chapters = best[n]

    booklets: list[ChapterBookletRange] = []
    start_chapter = 1
    start_page = 1
    for index, end_chapter in enumerate(end_chapters):
        original = sum(chapter_pages[start_chapter - 1 : end_chapter])
        booklets.append(
            ChapterBookletRange(
                index=index,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                start_page=start_page,
                end_page=start_page + original - 1,
                padded_pages=_ceil_to_multiple_of_four(original),
            )
        )
        start_chapter = end_chapter + 1
        start_page += original
    return booklets


def build_chapter_imposition(
    chapter_pages: list[int], max_sheets_per_booklet: int
) -> dict:
    """按章节最优分册并拼版。

    返回每册的章节序号范围、全局原稿页码范围、纸张数与补白数，以及与
    :func:`build_imposition` 一致的正反面左右拼版结构（补白为 ``None``）。
    调用方（schema 层）需已保证章节页数为正整数且单章不超容量。
    """
    booklets = split_chapter_booklets(chapter_pages, max_sheets_per_booklet)
    result_booklets: list[dict] = []

    for booklet in booklets:
        result_booklets.append(
            {
                "index": booklet.index,
                "start_chapter": booklet.start_chapter,
                "end_chapter": booklet.end_chapter,
                "start_page": booklet.start_page,
                "end_page": booklet.end_page,
                "original_pages": booklet.original_pages,
                "padded_pages": booklet.padded_pages,
                "blank_pages": booklet.blank_pages,
                "sheet_count": booklet.sheet_count,
                "sheets": _impose_booklet_sheets(booklet),
            }
        )

    return {
        "chapter_pages": list(chapter_pages),
        "max_sheets_per_booklet": max_sheets_per_booklet,
        "total_pages": sum(chapter_pages),
        "booklet_count": len(booklets),
        "total_sheets": sum(b.sheet_count for b in booklets),
        "booklets": result_booklets,
    }


def build_reprint(
    total_pages: int,
    max_sheets_per_booklet: int,
    damaged_ranges: Iterable[tuple[int, int]],
) -> dict:
    """按现有分册与拼版规则，定位承载受损原稿页的整张纸（补印清单）。

    ``damaged_ranges`` 为若干 ``(start_page, end_page)`` 闭区间（1-based），
    调用方（schema 层）需已保证区间非倒置、未越界且列表非空。

    - 区间允许相互交叠：同一纸张只返回一次；
    - 结果按分册序号升序、同册纸张从外到内（序号升序）排列；
    - 每张纸给出正反面左右原稿页码（补白为 ``None``）以及落在该纸上的、
      去重升序排列的受损页码。
    """
    damaged_pages: set[int] = set()
    for start, end in damaged_ranges:
        damaged_pages.update(range(start, end + 1))

    imposition = build_imposition(total_pages, max_sheets_per_booklet)
    sheets_out: list[dict] = []

    for booklet in imposition["booklets"]:
        for sheet in booklet["sheets"]:
            page_positions = (
                sheet["front"]["left"],
                sheet["front"]["right"],
                sheet["back"]["left"],
                sheet["back"]["right"],
            )
            hit = sorted(p for p in page_positions if p in damaged_pages)
            if not hit:
                continue
            # build_imposition 的输出本就按分册序号、纸张从外到内排列。
            sheets_out.append(
                {
                    "booklet_index": booklet["index"],
                    "sheet_index": sheet["index"],
                    "front": sheet["front"],
                    "back": sheet["back"],
                    "damaged_pages": hit,
                }
            )

    return {
        "total_pages": total_pages,
        "max_sheets_per_booklet": max_sheets_per_booklet,
        "booklet_count": imposition["booklet_count"],
        "reprint_sheet_count": len(sheets_out),
        "sheets": sheets_out,
    }
