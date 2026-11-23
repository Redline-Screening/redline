"""Shared page elements."""
import streamlit as st

# Containers with a key starting "panel" are drawn as white panels.
_CSS = """
<style>
[class*="st-key-panel"], [data-testid="stForm"] { background: #FFFFFF; }
</style>
"""


def apply_style() -> None:
    st.html(_CSS)


def page_header(title: str, subtitle: str) -> None:
    st.title(title, anchor=False)
    st.caption(subtitle)


def empty_panel(key: str, text: str) -> None:
    with st.container(border=True, key=f"panel-{key}"):
        st.write(text)
