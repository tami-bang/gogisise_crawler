import unittest

from app.service import CrawlerService


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


if __name__ == "__main__":
    unittest.main()
