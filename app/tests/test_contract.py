import datetime
import unittest

from pydantic import ValidationError

from models import BulkPayload, RawRecord


KST = datetime.timezone(datetime.timedelta(hours=9))


def valid_record(**overrides):
    values = {
        "collectedAt": datetime.datetime(2026, 7, 15, 3, 0, tzinfo=KST),
        "rawProductName": "금천한우/냉장/안심/1+",
        "pricePerKg": 38000,
        "species": "BEEF",
        "storageType": "CHILLED",
        "grade": "1+",
        "ageMonths": 28,
    }
    values.update(overrides)
    return RawRecord(**values)


class RawRecordContractTests(unittest.TestCase):
    def test_valid_record_serializes_iso_timestamp(self):
        record = valid_record()
        self.assertEqual(
            record.model_dump(mode="json")["collectedAt"],
            "2026-07-15T03:00:00+09:00",
        )

    def test_rejects_non_kst_timestamp(self):
        with self.assertRaises(ValidationError):
            valid_record(
                collectedAt=datetime.datetime.now(tz=datetime.timezone.utc)
            )

    def test_rejects_string_pricePerKg(self):
        with self.assertRaises(ValidationError):
            valid_record(pricePerKg=10000, brand="test", category="test", "38000")

    def test_rejects_pork_age(self):
        with self.assertRaises(ValidationError):
            valid_record(species="PORK", ageMonths=12)

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            valid_record(goodsNo="unexpected")

    def test_bulk_payload_is_limited_to_100(self):
        with self.assertRaises(ValidationError):
            BulkPayload(records=[valid_record()] * 101)


if __name__ == "__main__":
    unittest.main()
