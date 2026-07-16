import datetime
import unittest

from scraper import map_item_to_record


KST = datetime.timezone(datetime.timedelta(hours=9))
COLLECTED_AT = datetime.datetime(2026, 7, 15, 3, 0, tzinfo=KST)


class ItemMappingTests(unittest.TestCase):
    def test_normalizes_valid_source_item(self):
        record = map_item_to_record(
            {
                "goodsNm": "  금천한우/냉장/안심  ",
                "salePrc": "38,000",
                "lsspeNm": "한우",
                "strgMthdGbCd": "1",
                "lsprdGrdNm": "1+",
                "mage": "28",
            },
            COLLECTED_AT,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.price, 38000)
        self.assertEqual(record.rawProductName, "금천한우/냉장/안심")

    def test_skips_missing_required_source_field(self):
        record = map_item_to_record(
            {
                "goodsNm": "상품",
                "salePrc": None,
                "lsspeNm": "한우",
                "strgMthdGbCd": "1",
            },
            COLLECTED_AT,
        )
        self.assertIsNone(record)

    def test_pork_age_is_always_null(self):
        record = map_item_to_record(
            {
                "goodsNm": "금천한돈/냉장/삼겹살",
                "salePrc": 21000,
                "lsspeNm": "한돈",
                "strgMthdGbCd": "1",
                "mage": "12",
            },
            COLLECTED_AT,
        )
        self.assertIsNotNone(record)
        self.assertIsNone(record.ageInMonths)


if __name__ == "__main__":
    unittest.main()
