import os
from collections.abc import Callable
from typing import Any, TypedDict, cast


class ConfigError(Exception):
    pass


_SUPPORTED_PRIMITIVES: dict[type[Any], Callable[[str], Any]] = {
    str: str,
    int: int,
}


class Environment(TypedDict):
    auth_url: str
    public_key_url: str
    api_key_secret_name: str
    ddb_index_tag: str
    mock_table_name: str


_environment: Environment | None = None


def get_environment_variable[T](name: str, _type: type[T]) -> T:
    value = get_optional_environment_variable(name=name, _type=_type)
    if value is None:
        raise ConfigError(f"Environment variable {name!r} is not set")
    return value


def get_optional_environment_variable[T](name: str, _type: type[T]) -> T | None:
    value = os.getenv(name)

    match _type:
        case _ if _type in _SUPPORTED_PRIMITIVES:
            if value is None:
                return None

            return cast("T", _SUPPORTED_PRIMITIVES[_type](value))

        case _:
            raise ValueError(
                f"Required type {_type} is not supported for config values"
            )


def values() -> Environment:
    global _environment
    if _environment is None:
        _environment = Environment(
            auth_url=get_environment_variable("AUTH_URL", str),
            public_key_url=get_environment_variable("PUBLIC_KEY_URL", str),
            api_key_secret_name=get_environment_variable("API_KEY_SECRET_NAME", str),
            ddb_index_tag=get_environment_variable("DDB_INDEX_TAG", str),
            mock_table_name=get_environment_variable("MOCK_TABLE_NAME", str),
        )
    return _environment
