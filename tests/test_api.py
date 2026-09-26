"""API 层测试（需先安装 requirements-dev.txt：fastapi / httpx）。

运行方式：
    pip install -r requirements-dev.txt
    python -m unittest discover -s tests -v
"""

import unittest

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestImposeEndpoint(unittest.TestCase):
    def test_valid_post_request(self):
        resp = client.post(
            "/api/v1/impose",
            json={"total_pages": 16, "max_sheets_per_booklet": 4},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_pages"], 16)
        self.assertEqual(data["booklet_count"], 1)
        self.assertEqual(data["total_sheets"], 4)
        outer = data["booklets"][0]["sheets"][0]
        self.assertEqual(outer["front"], {"left": 16, "right": 1})
        self.assertEqual(outer["back"], {"left": 2, "right": 15})

    def test_blank_page_is_null(self):
        resp = client.post(
            "/api/v1/impose",
            json={"total_pages": 5, "max_sheets_per_booklet": 10},
        )
        self.assertEqual(resp.status_code, 200)
        booklet = resp.json()["booklets"][0]
        self.assertEqual(booklet["blank_pages"], 3)
        self.assertEqual(booklet["sheets"][0]["front"]["left"], None)

    def test_get_equivalent(self):
        resp = client.get("/api/v1/impose?total_pages=8&max_sheets_per_booklet=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["booklets"][0]["sheets"][0]["front"], {"left": 8, "right": 1})

    def test_health(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class TestInvalidInputs(unittest.TestCase):
    def _assert_400(self, payload):
        resp = client.post("/api/v1/impose", json=payload)
        self.assertEqual(resp.status_code, 400, payload)
        body = resp.json()
        self.assertEqual(body["error"], "invalid_input")
        self.assertIn("details", body)
        return body

    def test_zero_rejected(self):
        body = self._assert_400(
            {"total_pages": 0, "max_sheets_per_booklet": 2}
        )
        self.assertIn("total_pages", body["details"][0]["field"])

    def test_negative_rejected(self):
        self._assert_400({"total_pages": 16, "max_sheets_per_booklet": -1})

    def test_float_rejected(self):
        self._assert_400({"total_pages": 16.5, "max_sheets_per_booklet": 2})

    def test_integer_float_rejected(self):
        # 16.0 这类“看起来是整数”的浮点数也必须拒绝
        self._assert_400({"total_pages": 16.0, "max_sheets_per_booklet": 2})

    def test_string_rejected(self):
        self._assert_400({"total_pages": "16", "max_sheets_per_booklet": 2})

    def test_boolean_rejected(self):
        self._assert_400({"total_pages": True, "max_sheets_per_booklet": 2})

    def test_null_rejected(self):
        self._assert_400({"total_pages": None, "max_sheets_per_booklet": 2})

    def test_missing_field_rejected(self):
        self._assert_400({"total_pages": 16})

    def test_extra_field_rejected(self):
        self._assert_400(
            {"total_pages": 16, "max_sheets_per_booklet": 2, "duplex": True}
        )

    def test_get_invalid_query_rejected(self):
        resp = client.get("/api/v1/impose?total_pages=abc&max_sheets_per_booklet=2")
        self.assertEqual(resp.status_code, 400)
        resp = client.get("/api/v1/impose?total_pages=0&max_sheets_per_booklet=2")
        self.assertEqual(resp.status_code, 400)
        resp = client.get("/api/v1/impose?total_pages=16&max_sheets_per_booklet=2.5")
        self.assertEqual(resp.status_code, 400)


class TestReprintEndpoint(unittest.TestCase):
    REPRINT_URL = "/api/v1/reprint"

    def test_valid_reprint_single_range(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [{"start_page": 1, "end_page": 4}],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["reprint_sheet_count"], 2)
        self.assertEqual(
            [
                (s["booklet_index"], s["sheet_index"], s["damaged_pages"])
                for s in data["sheets"]
            ],
            [(0, 0, [1, 2]), (0, 1, [3, 4])],
        )
        outer = data["sheets"][0]
        self.assertEqual(outer["front"], {"left": 16, "right": 1})
        self.assertEqual(outer["back"], {"left": 2, "right": 15})

    def test_overlapping_ranges_dedupe_sheets(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [
                    {"start_page": 1, "end_page": 2},
                    {"start_page": 2, "end_page": 1},
                ],
            },
        )
        # 第二项区间倒置 -> 400
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_input")

        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [
                    {"start_page": 1, "end_page": 3},
                    {"start_page": 2, "end_page": 8},
                ],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        # 并集 1..8 -> 4 张纸，纸张不重复
        self.assertEqual(data["reprint_sheet_count"], 4)
        keys = [(s["booklet_index"], s["sheet_index"]) for s in data["sheets"]]
        self.assertEqual(keys, [(0, 0), (0, 1), (0, 2), (0, 3)])
        self.assertEqual(
            [p for s in data["sheets"] for p in s["damaged_pages"]],
            [1, 2, 3, 4, 5, 6, 7, 8],
        )

    def test_multi_booklet_ordering(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 17,
                "max_sheets_per_booklet": 2,
                "damaged_ranges": [{"start_page": 17, "end_page": 17}],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        sheets = resp.json()["sheets"]
        self.assertEqual(len(sheets), 1)
        self.assertEqual(
            (sheets[0]["booklet_index"], sheets[0]["sheet_index"]), (2, 0)
        )
        self.assertEqual(sheets[0]["damaged_pages"], [17])
        # 最后一册补白以 null 表示
        self.assertIn(None, sheets[0]["front"].values())
        self.assertIn(None, sheets[0]["back"].values())

    def test_empty_ranges_rejected(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [],
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["error"], "invalid_input")
        self.assertTrue(
            any("damaged_ranges" in d["field"] for d in body["details"])
        )

    def test_reversed_range_rejected(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [{"start_page": 5, "end_page": 3}],
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertTrue(any("倒置" in d["message"] for d in body["details"]))

    def test_out_of_bounds_rejected(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [{"start_page": 15, "end_page": 17}],
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertTrue(any("越界" in d["message"] for d in body["details"]))

    def test_missing_ranges_rejected(self):
        resp = client.post(
            self.REPRINT_URL,
            json={"total_pages": 16, "max_sheets_per_booklet": 4},
        )
        self.assertEqual(resp.status_code, 400)

    def test_bad_range_item_rejected(self):
        # 区间项必须是对象
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [[1, 4]],
            },
        )
        self.assertEqual(resp.status_code, 400)

        # 区间端点必须为正整数
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [{"start_page": 0, "end_page": 4}],
            },
        )
        self.assertEqual(resp.status_code, 400)

        # 多余字段
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [
                    {"start_page": 1, "end_page": 4, "note": "x"}
                ],
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_common_field_validation_still_400(self):
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 0,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": [{"start_page": 1, "end_page": 1}],
            },
        )
        self.assertEqual(resp.status_code, 400)
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": True,
                "damaged_ranges": [{"start_page": 1, "end_page": 1}],
            },
        )
        self.assertEqual(resp.status_code, 400)
        resp = client.post(
            self.REPRINT_URL,
            json={
                "total_pages": 16,
                "max_sheets_per_booklet": 4,
                "damaged_ranges": "1-4",
            },
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
