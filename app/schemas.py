"""请求 / 响应数据模型。"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError


class ImpositionRequest(BaseModel):
    """拼版请求。

    ``StrictInt`` 会拒绝布尔值、浮点数与数字字符串，只接受真正的整数；
    ``ge=1`` 进一步保证为正整数。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    total_pages: StrictInt = Field(
        ..., ge=1, description="原稿总页数，必须为正整数。", examples=[16]
    )
    max_sheets_per_booklet: StrictInt = Field(
        ...,
        ge=1,
        description="每册最多纸张数（1 张纸正反 4 个版面），必须为正整数。",
        examples=[2],
    )


class SidePages(BaseModel):
    left: int | None = Field(..., description="左侧页码；null 表示空白页。")
    right: int | None = Field(..., description="右侧页码；null 表示空白页。")


class SheetLayout(BaseModel):
    index: int = Field(..., description="纸张序号，0 为最外侧纸张。")
    front: SidePages = Field(..., description="正面（朝外一面）左右页码。")
    back: SidePages = Field(..., description="反面（朝内一面）左右页码。")


class BookletLayout(BaseModel):
    index: int = Field(..., description="分册序号，从 0 开始。")
    start_page: int = Field(..., description="本册起始原稿页码（含）。")
    end_page: int = Field(..., description="本册结束原稿页码（含）。")
    original_pages: int = Field(..., description="本册原稿页数。")
    padded_pages: int = Field(..., description="补齐后的版面页数（4 的倍数）。")
    blank_pages: int = Field(..., description="补位空白页数。")
    sheet_count: int = Field(..., description="本册实际用纸张数。")
    sheets: list[SheetLayout] = Field(..., description="纸张列表，从外到内。")


class ImpositionResponse(BaseModel):
    total_pages: int
    max_sheets_per_booklet: int
    booklet_count: int = Field(..., description="分册数量。")
    total_sheets: int = Field(..., description="全部册合计用纸张数。")
    booklets: list[BookletLayout]


class DamagedRange(BaseModel):
    """一段受损原稿页区间（端点均包含，1-based）。"""

    model_config = ConfigDict(extra="forbid")

    start_page: StrictInt = Field(..., ge=1, description="受损区间起始页（含）。")
    end_page: StrictInt = Field(..., ge=1, description="受损区间结束页（含）。")


class ReprintRequest(BaseModel):
    """补印请求：总页数、每册最多纸张数与非空的受损页区间列表。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    total_pages: StrictInt = Field(
        ..., ge=1, description="原稿总页数，必须为正整数。", examples=[16]
    )
    max_sheets_per_booklet: StrictInt = Field(
        ...,
        ge=1,
        description="每册最多纸张数（1 张纸正反 4 个版面），必须为正整数。",
        examples=[4],
    )
    damaged_ranges: list[DamagedRange] = Field(
        ...,
        min_length=1,
        description="受损原稿页区间列表（至少一项），端点均包含，允许交叠。",
    )

    @field_validator("damaged_ranges")
    @classmethod
    def _validate_ranges(
        cls, ranges: list[DamagedRange], info: ValidationInfo
    ) -> list[DamagedRange]:
        total_pages = info.data.get("total_pages")
        for range_ in ranges:
            if range_.start_page > range_.end_page:
                raise PydanticCustomError(
                    "reversed_range",
                    "受损页区间不能倒置：start_page 必须小于等于 end_page。",
                )
            # total_pages 自身非法（缺失 / 非正整数）时已有对应校验错误，跳过越界检查。
            if total_pages is not None and range_.end_page > total_pages:
                raise PydanticCustomError(
                    "page_out_of_range",
                    "受损页区间越界：页码必须在 1 到 total_pages 之间。",
                )
        return ranges


class ReprintSheet(BaseModel):
    booklet_index: int = Field(..., description="分册序号，从 0 开始。")
    sheet_index: int = Field(..., description="纸张序号，0 为该册最外侧纸张。")
    front: SidePages = Field(..., description="正面（朝外一面）左右页码。")
    back: SidePages = Field(..., description="反面（朝内一面）左右页码。")
    damaged_pages: list[int] = Field(
        ..., description="落在该纸上的受损原稿页码，去重并升序排列。"
    )


class ReprintResponse(BaseModel):
    total_pages: int
    max_sheets_per_booklet: int
    booklet_count: int = Field(..., description="分册数量。")
    reprint_sheet_count: int = Field(..., description="需要补印的整张纸数量（已去重）。")
    sheets: list[ReprintSheet] = Field(
        ..., description="需补印的纸张，按分册序号、纸张从外到内排序。"
    )


class ChapterImpositionRequest(BaseModel):
    """按章节拼版请求：非空的有序章节页数数组 + 每册最多纸张数。

    章节不可拆分、仅相邻章节可合册，因此单章页数不得超过
    ``4 * max_sheets_per_booklet``，否则无法成册。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chapter_pages: list[Annotated[StrictInt, Field(ge=1)]] = Field(
        ...,
        min_length=1,
        description="有序章节页数数组，每项为正整数，至少一章。",
        examples=[[4, 4, 4, 4]],
    )
    max_sheets_per_booklet: StrictInt = Field(
        ...,
        ge=1,
        description="每册最多纸张数（每册最多 4 × 该值 个版面），必须为正整数。",
        examples=[2],
    )

    @model_validator(mode="after")
    def _check_chapter_capacity(self) -> "ChapterImpositionRequest":
        capacity = 4 * self.max_sheets_per_booklet
        for position, pages in enumerate(self.chapter_pages, start=1):
            if pages > capacity:
                raise PydanticCustomError(
                    "chapter_too_large",
                    "第 {position} 章共 {pages} 页，超过每册容量上限 {capacity} 页"
                    "（4 × max_sheets_per_booklet），章节不可拆分。",
                    {
                        "position": position,
                        "pages": pages,
                        "capacity": capacity,
                    },
                )
        return self


class ChapterBookletLayout(BaseModel):
    index: int = Field(..., description="分册序号，从 0 开始。")
    start_chapter: int = Field(..., description="本册起始章节序号（含，从 1 开始）。")
    end_chapter: int = Field(..., description="本册结束章节序号（含，从 1 开始）。")
    start_page: int = Field(..., description="本册起始全局原稿页码（含）。")
    end_page: int = Field(..., description="本册结束全局原稿页码（含）。")
    original_pages: int = Field(..., description="本册原稿页数。")
    padded_pages: int = Field(..., description="补齐后的版面页数（4 的倍数）。")
    blank_pages: int = Field(..., description="补位空白页数。")
    sheet_count: int = Field(..., description="本册实际用纸张数。")
    sheets: list[SheetLayout] = Field(..., description="纸张列表，从外到内。")


class ChapterImpositionResponse(BaseModel):
    chapter_pages: list[int] = Field(..., description="回显输入的章节页数数组。")
    max_sheets_per_booklet: int
    total_pages: int = Field(..., description="全部章节合计原稿页数。")
    booklet_count: int = Field(..., description="分册数量。")
    total_sheets: int = Field(..., description="全部册合计用纸张数。")
    booklets: list[ChapterBookletLayout]
