from __future__ import annotations

from src.data.real_tour_audit import install_keyring_mutation_guard


class RealTourStartupService:
    """Installs Real Grand Tour runtime guards through a business facade."""

    def install_runtime_guards(self) -> None:
        install_keyring_mutation_guard()
