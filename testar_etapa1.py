"""
testar_etapa1.py — Entrypoint mínimo pra testar só a Etapa 1.

Rode com:
    streamlit run testar_etapa1.py

O que faz:
- Sobe os arquivos.
- Roda a Etapa 1 (classificação + detecção de categoria/modelo).
- Exibe o checkpoint de confirmação.
- Aceita correções via chat.
- Exibe "confirmado" quando o usuário aprovar.

Não substitui o app_v2.py — é só pra você validar a Etapa 1 antes de
empilhar as demais. Quando tudo estiver pronto, isso vira parte do app_v2.py.
"""

import streamlit as st
from estudo import Estudo
from etapa1 import rodar_etapa1, aplicar_correcao_etapa1

st.set_page_config(page_title="Etapa 1 — Classificação", layout="wide")
st.title("Etapa 1 — Classificação dos Documentos")
st.caption("Entrypoint de teste. Sobe os arquivos e veja o resultado da Etapa 1.")

# --- Estado da sessão ---
if "estudo" not in st.session_state:
    st.session_state.estudo = Estudo()
if "etapa1_resultado" not in st.session_state:
    st.session_state.etapa1_resultado = None
if "etapa1_confirmada" not in st.session_state:
    st.session_state.etapa1_confirmada = False
if "historico_chat" not in st.session_state:
    st.session_state.historico_chat = []

estudo = st.session_state.estudo

# --- Upload ---
if not st.session_state.etapa1_confirmada:
    arquivos = st.file_uploader(
        "Suba os arquivos do processo (edital, propostas, baseline...)",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
        key="upload_etapa1",
    )

    if arquivos and st.session_state.etapa1_resultado is None:
        resultado = rodar_etapa1(estudo, arquivos)
        st.session_state.etapa1_resultado = resultado
        st.session_state.historico_chat.append(
            {"role": "assistant", "content": resultado["resumo_checkpoint"]}
        )

# --- Exibir histórico do chat ---
for msg in st.session_state.historico_chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Input do chat ---
if st.session_state.etapa1_resultado and not st.session_state.etapa1_confirmada:
    entrada = st.chat_input("Confirme ou corrija aqui...")
    if entrada:
        st.session_state.historico_chat.append({"role": "user", "content": entrada})

        entrada_lower = entrada.lower().strip()
        palavras_confirmacao = {"confirmo", "ok", "sim", "correto", "certo", "pode seguir", "confirmado", "tá bom", "ta bom"}

        if any(p in entrada_lower for p in palavras_confirmacao):
            estudo.etapa_atual = 2  # Libera pra próxima etapa
            st.session_state.etapa1_confirmada = True
            resposta = (
                "✅ **Etapa 1 confirmada.**\n\n"
                f"- **Categoria:** {estudo.categoria}\n"
                f"- **Modelo de precificação:** {estudo.modelo_precificacao}\n"
                f"- **Documentos classificados:** {len(estudo.documentos)}\n\n"
                "Quando o app completo estiver pronto, a Etapa 2 começa aqui."
            )
        else:
            resposta = aplicar_correcao_etapa1(estudo, entrada)

        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

elif st.session_state.etapa1_confirmada:
    st.success("Etapa 1 confirmada. Pronto pra receber a Etapa 2.")

    # Resumo do estado final do Estudo
    with st.expander("Ver estado do Estudo após Etapa 1"):
        st.write("**Categoria:**", estudo.categoria)
        st.write("**Modelo de precificação:**", estudo.modelo_precificacao)
        st.write("**Documentos:**")
        for d in estudo.documentos:
            st.write(f"- {d['nome']} → `{d['tipo']}`", f"(fornecedor: {d.get('fornecedor', '—')})")
        if estudo.faltantes:
            st.write("**Faltantes registrados:**")
            for f in estudo.faltantes:
                st.write(f"- {f}")
        if estudo.premissas:
            st.write("**Premissas registradas:**")
            for p in estudo.premissas:
                st.write(f"- {p}")
