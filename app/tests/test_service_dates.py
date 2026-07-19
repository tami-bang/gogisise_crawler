import unittest

from app.service import CrawlerService, normalize_source_date


class SourceDateMappingTests(unittest.TestCase):
    def setUp(self):
        self.service = CrawlerService()

    def test_maps_geumcheon_manufacture_and_expiry_dates(self):
        result = self.service.process_and_analyze(
            "국내산 한우,국내산 한우 암소,금천한우(암),안심",
            [
                {
                    "goodsNo": "27101767",
                    "goodsNm": "금천미한우암소안심",
                    "brandNm": "금천미한우",
                    "artcCd": "1001010001",
                    "salePrc": 346140,
                    "useEnabWgt": "2.7",
                    "lsprdGrdNm": "1++",
                    "mage": "32",
                    "ppYmd": "20260707",
                    "distriDlineYmd": "20260904",
                    "distriDlineGbNm": "제조일로부터 60일",
                    "strgMthdGbCd": "1",
                    "lsspeNm": "한우",
                }
            ],
        )

        metadata = result["items"][0]["metadata"]
        self.assertEqual(metadata["mfg_date"], "20260707")
        self.assertEqual(metadata["expiry_date"], "20260904")

    def test_does_not_fabricate_missing_dates(self):
        self.assertIsNone(normalize_source_date(None))
        self.assertIsNone(normalize_source_date("20260230"))


if __name__ == "__main__":
    unittest.main()
