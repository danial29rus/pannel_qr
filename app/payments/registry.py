from app.payments.adapters.base import PaymentAdapter
from app.payments.adapters.demo import DemoProcessorAdapter
from app.payments.adapters.mulenpay import MulenPayAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PaymentAdapter] = {"demo": DemoProcessorAdapter()}

    def get(self, adapter_type: str, config: dict | None = None) -> PaymentAdapter:
        if adapter_type == "mulenpay":
            return MulenPayAdapter(config or {})
        try:
            return self._adapters[adapter_type]
        except KeyError as exc:
            raise ValueError(f"Adapter '{adapter_type}' is not registered") from exc


registry = AdapterRegistry()
