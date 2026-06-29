from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import storage
from core.models import Route, money
from core.routes import add_route, delete_route, load_routes, update_route
from core.sweep import run_sweep

st.set_page_config(page_title="PassagensApp", page_icon="✈️", layout="wide")
storage.init_db()


def safe_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        return storage.df(sql, params)
    except Exception:
        return pd.DataFrame()


def fmt_money(value, currency: str = "BRL") -> str:
    return money(value, currency) if pd.notna(value) else "-"


def route_title(route: Route) -> str:
    return f"{route.origin} -> {route.destination}"


st.markdown(
    """
<style>
.block-container { padding-top: 1rem; max-width: 1100px; }
.app-subtitle { color:#475569; font-size:.95rem; margin-top:-.5rem; margin-bottom:1rem; }
.route-card {
  border:1px solid #d7dee8;
  border-radius:8px;
  padding:14px 16px;
  background:#ffffff;
  margin-bottom:10px;
}
.route-title { font-weight:800; font-size:1.05rem; color:#0f172a; }
.price { font-weight:900; font-size:1.5rem; color:#15803d; margin-top:4px; }
.muted { color:#64748b; font-size:.88rem; }
.badge {
  display:inline-block;
  padding:4px 8px;
  border-radius:999px;
  font-size:.72rem;
  font-weight:800;
  margin-right:5px;
}
.on { background:#dcfce7; color:#166534; }
.off { background:#e5e7eb; color:#374151; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("PassagensApp")
st.markdown(
    '<div class="app-subtitle">Google Flights apenas. Menor preco por rota.</div>',
    unsafe_allow_html=True,
)

routes = load_routes()
storage.sync_routes(routes)
route_ids = {r.id for r in routes}
active_routes = [r for r in routes if r.is_active]

summary = safe_df(
    """
WITH best AS (
  SELECT *
  FROM (
    SELECT
      p.*,
      ROW_NUMBER() OVER (
        PARTITION BY p.route_id
        ORDER BY p.price ASC, p.departure_date ASC, p.return_date ASC
      ) AS rn
    FROM price_snapshots p
    WHERE p.snapshot_kind = 'TOTAL'
  )
  WHERE rn = 1
),
latest AS (
  SELECT route_id, MAX(fetched_at) AS last_fetch
  FROM price_snapshots
  GROUP BY route_id
)
SELECT
  r.id AS route_id,
  r.origin,
  r.destination,
  r.label,
  r.is_active,
  b.departure_date AS ida,
  b.return_date AS volta,
  b.price AS preco,
  b.currency,
  b.data_source AS fonte,
  l.last_fetch
FROM routes r
LEFT JOIN best b ON b.route_id = r.id
LEFT JOIN latest l ON l.route_id = r.id
ORDER BY r.is_active DESC, r.origin, r.destination
"""
)
if not summary.empty:
    summary = summary[summary["route_id"].isin(route_ids)].copy()

with st.sidebar:
    st.header("Busca")
    if st.button("Rodar agora", type="primary", use_container_width=True):
        with st.spinner("Buscando menor preco no Google Flights..."):
            try:
                result = run_sweep()
                st.success(
                    f"OK: {result['routes_success']}/{result['routes_total']} rotas, "
                    f"{result['snapshots_saved']} snapshots."
                )
            except RuntimeError as exc:
                st.warning(str(exc))
        st.rerun()

    st.divider()
    st.header("Rotas ativas")
    if active_routes:
        for route in active_routes:
            st.write(route_title(route))
    else:
        st.write("Nenhuma rota ativa.")

st.subheader("Adicionar rota")
with st.form("quick_add_route", clear_on_submit=False):
    c1, c2 = st.columns(2)
    origin = c1.text_input("Origem", value="BSB").upper().strip()
    destination = c2.text_input("Destino", value="IGU").upper().strip()
    submitted = st.form_submit_button("Adicionar")
    if submitted:
        if not origin or not destination:
            st.error("Informe origem e destino.")
        else:
            route = Route(
                id=str(uuid.uuid4()),
                origin=origin,
                destination=destination,
                trip_type="ROUND_TRIP",
                trip_duration=7,
                currency="BRL",
                is_active=True,
                label=f"{origin} -> {destination}",
                split_legs=True,
            )
            add_route(route)
            storage.upsert_route(route)
            st.success("Rota adicionada.")
            st.rerun()

st.subheader("Rotas monitoradas")
if summary.empty:
    st.info("Nenhuma rota cadastrada.")
else:
    for _, row in summary.iterrows():
        route_id = row["route_id"]
        is_active = bool(row["is_active"])
        status = '<span class="badge on">ON</span>' if is_active else '<span class="badge off">OFF</span>'
        currency = row["currency"] if pd.notna(row["currency"]) else "BRL"
        total = fmt_money(row["preco"], currency)
        st.markdown(
            f"""
            <div class="route-card">
              <div class="route-title">{row['origin']} -> {row['destination']}</div>
              <div>{status}</div>
              <div class="price">{total}</div>
              <div class="muted">Ida: {row['ida'] or '-'} | Volta: {row['volta'] or '-'} | Ultima busca: {row['last_fetch'] or '-'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        if c1.button("Pausar" if is_active else "Ativar", key=f"toggle_{route_id}"):
            target = next((r for r in load_routes() if r.id == route_id), None)
            if target:
                target.is_active = not target.is_active
                update_route(route_id, target)
                storage.upsert_route(target)
                st.rerun()
        if c2.button("Excluir", key=f"delete_{route_id}"):
            delete_route(route_id)
            st.rerun()
