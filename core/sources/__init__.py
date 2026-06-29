"""
Registry de fontes do PassagensApp.

Estados possiveis por fonte:
  protegida    - roda de verdade e entra no sweep por padrao
  experimental - pode ser registrada, mas fica fora do sweep por padrao
  pendente     - alvo real de implementacao futura
  catalogo     - referencia/estudo, fora do fluxo

A fonte protegida nao deve ser afetada por testes de novas fontes.
"""
from __future__ import annotations

from core.config import settings
from core.sources.fli_source import FliSource
from kiwi_adapter import KiwiMcpSource

PROTECTED_SOURCE_NAMES = {"google_flights"}

_PROTECTED: list = [
    FliSource(),
]

_EXPERIMENTAL: list = [
    KiwiMcpSource(),
]

# Fontes pendentes (nao instanciar - so documentar)
# browser_voosbaratos  -> pendente: testada localmente, aguarda reintegracao
# browser_booking      -> pendente: Playwright UI em andamento
# browser_decolar      -> pendente: abordagem diferente necessaria
# browser_kiwi         -> pendente
# browser_skyscanner   -> pendente
# browser_kayak        -> pendente


def enabled_sources() -> list:
    """Retorna a fonte protegida e, se liberadas, fontes experimentais."""
    sources = list(_PROTECTED)
    if settings.allow_experimental_sources:
        sources.extend(_EXPERIMENTAL)
    return sources


def register_source(source) -> None:
    """
    Registra uma fonte adicional sem afetar o fluxo principal.
    Por padrao ela fica fora do sweep; para testar, defina
    ALLOW_EXPERIMENTAL_SOURCES=1 no ambiente.

    Exemplo:
        from core.sources.browser_voosbaratos import BrowserVoosBaratosSource
        register_source(BrowserVoosBaratosSource())
    """
    if getattr(source, "name", None) in PROTECTED_SOURCE_NAMES:
        raise ValueError(f"fonte protegida ja registrada: {source.name}")
    _EXPERIMENTAL.append(source)
