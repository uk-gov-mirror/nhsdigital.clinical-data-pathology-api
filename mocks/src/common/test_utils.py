from common.utils import check_valid_uuid4


class TestUtils:
    def test_check_valid_uuid_with_valid_uuid(self) -> None:
        assert check_valid_uuid4("8c64be5f-3d7a-4b7b-8260-b716d122bdaf")

    def test_check_valid_uuid_with_invalid_uuid(self) -> None:
        assert not check_valid_uuid4("invalid-uuid")
