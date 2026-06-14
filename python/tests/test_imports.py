"""Sprint 0 smoke test: the package imports and exposes its core surface."""

import importlib

import pytest


def test_package_imports():
    pkg = importlib.import_module("alpaca_quant")
    assert pkg.__version__


def test_alpha_interface_and_registry_import():
    from alpaca_quant.alphas import Alpha, AlphaMetadata, get, register, registered_names

    # Abstract: cannot be instantiated directly.
    with pytest.raises(TypeError):
        Alpha()  # type: ignore[abstract]

    meta = AlphaMetadata(name="dummy", horizon="1d", capacity_usd=1_000_000)
    assert meta.name == "dummy"

    # Registry round-trip with a trivial concrete alpha.
    class _Dummy(Alpha):
        @property
        def metadata(self) -> AlphaMetadata:
            return meta

        def compute(self, features):  # noqa: ANN001 - test stub
            return None

    register("dummy", _Dummy())
    assert "dummy" in registered_names()
    assert isinstance(get("dummy"), Alpha)
