"""
ia.py — Conversa com o Claude.

Inicializa o cliente da API usando a sua chave (lida dos Secrets do
Streamlit) e oferece uma função única, call_claude(), que todas as
8 etapas vão usar pra pedir uma resposta ao modelo.

Portado do app.py atual, sem mudança de comportamento.
"""

import os
import streamlit as st
import anthropic

from config import MODEL


def get_client():
    """Inicializa o cliente Anthropic com a chave da API."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("⚠️ Chave da API do Claude não configurada. Veja o GUIA-DEPLOY.md para configurar.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


def call_claude(messages, system, max_tokens=2000):
    """Chama a API do Claude e devolve o texto da resposta."""
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text
