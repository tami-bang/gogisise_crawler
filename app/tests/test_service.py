import unittest

from app.service import CrawlerService, is_sellable_item


class CrawlerServiceItemTests(unittest.TestCase):
    def test_keeps_sellable_ungraded_beef_byproduct(self):
        result = CrawlerService().process_and_analyze(
            "국내산 한우,국내산 한우 암소,금천한우(암),알꼬리",
            [
                {
                    "goodsNm": "한우암소냉동알꼬리(외부)",
                    "goodsNo": "27068868",
                    "artcCd": "100101",
                    "brandNm": "금천한우",
                    "lsspeNm": "한우",
                    "strgMthdGbCd": "2",
                    "lsprdGrdNm": "해당없음",
                    "mage": None,
                    "useEnabWgt": "11.9",
                    "salePrc": 333200,
                }
            ],
        )

        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["items"][0]["metadata"]["age"])
        self.assertIsNone(result["items"][0]["metadata"]["grade"])

    def test_rejects_placeholder_without_sellable_fields(self):
        result = CrawlerService().process_and_analyze(
            "국내산 돈육,국내산 돈육,맛봄,냉동미박앞다리",
            [
                {
                    "goodsNm": "맛봄-냉동미박앞다리",
                    "goodsNo": None,
                    "lsspeNm": "한돈",
                    "strgMthdGbCd": "2",
                    "salePrc": 0,
                }
            ],
        )

        self.assertEqual(result["items"], [])

    def test_rejects_sold_out_and_zero_stock_items(self):
        base_item = {
            "goodsNm": "금천한우암소안심",
            "goodsNo": "SOLD-OUT",
            "lsspeNm": "한우",
            "strgMthdGbCd": "1",
            "lsprdGrdNm": "1+",
            "useEnabWgt": "3.0",
            "salePrc": 300000,
        }

        for state in (
            {"saleFnshYn": "Y"},
            {"saleStatNm": "품절"},
            {"saleStatCd": "20"},
            {"itmSaleStatCd": "20"},
            {"stkQty": 0, "nolmtInvtYn": "N"},
            {"dispYn": "N"},
        ):
            with self.subTest(state=state):
                result = CrawlerService().process_and_analyze(
                    "국내산 한우,국내산 한우 암소,금천한우(암),안심",
                    [{**base_item, **state}],
                )
                self.assertEqual(result["items"], [])

    def test_allows_zero_stock_for_unlimited_inventory(self):
        self.assertTrue(is_sellable_item({"stkQty": 0, "nolmtInvtYn": "Y"}))


if __name__ == "__main__":
    unittest.main()
