import threading

from pathology_api.request_context import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)


class TestSetAndGetCorrelationId:
    def test_correlation_id_is_set_and_retrieved(self) -> None:
        set_correlation_id("round-trip-test-123")
        assert get_correlation_id() == "round-trip-test-123"
        reset_correlation_id()

    def test_correlation_id_is_cleared_after_reset(self) -> None:
        set_correlation_id("round-trip-test-123")
        reset_correlation_id()
        assert get_correlation_id() == ""

    def test_default_correlation_id_is_empty_string(self) -> None:
        assert get_correlation_id() == ""

    def test_correlation_id_is_cleared_when_reset_called_after_exception(
        self,
    ) -> None:
        try:
            set_correlation_id("will-be-cleared")
            raise RuntimeError("simulated mid-handler failure")
        except RuntimeError:
            pass
        finally:
            reset_correlation_id()

        assert get_correlation_id() == ""

    def test_correlation_id_does_not_bleed_between_threads(self) -> None:
        results: dict[str, str] = {}

        def thread_a() -> None:
            set_correlation_id("thread-a-id")
            import time

            time.sleep(0.05)
            results["a"] = get_correlation_id()
            reset_correlation_id()

        def thread_b() -> None:
            set_correlation_id("thread-b-id")
            results["b"] = get_correlation_id()
            reset_correlation_id()

        t_a = threading.Thread(target=thread_a)
        t_b = threading.Thread(target=thread_b)
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

        assert results["a"] == "thread-a-id"
        assert results["b"] == "thread-b-id"
