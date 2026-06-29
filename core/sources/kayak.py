from __future__ import annotations

from core.models import Route


class KayakSource:
    name = "kayak"

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        raise NotImplementedError(
            "Kayak precisa de adaptador Playwright/Selenium com controle anti-bot. "
            "Referencia estudada: github.com/soutes/busca_voo usa URLs do Kayak "
            "e extrai o bloco aria-label='Mais barato', mas ainda e fragil para VPS."
        )
