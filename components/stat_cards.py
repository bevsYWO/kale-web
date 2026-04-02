"""
components/stat_cards.py — Reusable stat card row using st.metric.
"""

import streamlit as st


def render_stat_cards(cards: list[dict]) -> None:
    """
    Render a row of metric cards.

    Each card dict should have:
      label  : str
      value  : int | str
      delta  : str | None  (optional)
      help   : str | None  (optional)

    Example:
        render_stat_cards([
            {"label": "Total Rows", "value": 500},
            {"label": "Cells Changed", "value": 42, "delta": "8%"},
        ])
    """
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.metric(
                label=card.get("label", ""),
                value=card.get("value", 0),
                delta=card.get("delta"),
                help=card.get("help"),
            )
