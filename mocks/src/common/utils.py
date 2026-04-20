import re


def check_valid_uuid4(string: str) -> bool:
    uuid_regex = (
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    return re.match(uuid_regex, string) is not None
