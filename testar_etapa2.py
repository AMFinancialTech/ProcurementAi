"""
testar_etapa2.py — Entrypoint pra testar Etapa 1 + Etapa 2 em sequência.

Rode com:
    streamlit run testar_etapa2.py

Fluxo:
1. Upload dos arquivos.
2. Etapa 1: classificação + checkpoint de confirmação.
3. Etapa 2: análise do baseline (micro-categoria, técnica, comercial,
   TCO, should-cost).
4. Se a anualização precisar de confirmação, pede via chatbox.
5. Exibe resumo completo e estado do Estudo ao final.
"""

import streamlit as st
from estudo import Estudo
from etapa1 import rodar_etapa1, aplicar_correcao_etapa1
from etapa2 import rodar_etapa2, confirmar_periodo_anualização

st.set_page_config(page_title="Etapas 1-2 — Teste", layout="wide")
st.title("Analisador de Propostas — Etapas 1 e 2")
st.caption("Entrypoint de teste. Etapa 1 (Classificação) + Etapa 2 (Baseline).")

# --- Estado da sessão ---
if "estudo" not in st.session_state:
    st.session_state.estudo = Estudo()
if "etapa1_resultado" not in st.session_state:
    st.session_state.etapa1_resultado = None
if "etapa1_confirmada" not in st.session_state:
    st.session_state.etapa1_confirmada = False
if "etapa2_resultado" not in st.session_state:
    st.session_state.etapa2_resultado = None
if "etapa2_anualização_ok" not in st.session_state:
    st.session_state.etapa2_anualização_ok = False
if "historico_chat" not in st.session_state:
    st.session_state.historico_chat = []

estudo = st.session_state.estudo

# --- Barra de progresso ---
etapa_atual = 0
if st.session_state.etapa1_resultado:
    etapa_atual = 1
if st.session_state.etapa1_confirmada:
    etapa_atual = 2
if st.session_state.etapa2_resultado:
    etapa_atual = 3

st.progress(etapa_atual / 3, text=f"Passo {etapa_atual} de 3")

# -----------------------------------------------------------------------
# UPLOAD
# -----------------------------------------------------------------------
if not st.session_state.etapa1_confirmada:
    arquivos = st.file_uploader(
        "Suba os arquivos do processo (edital, propostas, baseline...)",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
        key="upload",
    )

    if arquivos and st.session_state.etapa1_resultado is None:
        resultado = rodar_etapa1(estudo, arquivos)
        st.session_state.etapa1_resultado = resultado
        st.session_state.historico_chat.append(
            {"role": "assistant", "content": resultado["resumo_checkpoint"]}
        )
        st.rerun()

# -----------------------------------------------------------------------
# CHAT — exibe histórico
# -----------------------------------------------------------------------
for msg in st.session_state.historico_chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# -----------------------------------------------------------------------
# ETAPA 1 — checkpoint
# -----------------------------------------------------------------------
if st.session_state.etapa1_resultado and not st.session_state.etapa1_confirmada:
    entrada = st.chat_input("Confirme a classificação ou corrija aqui...")
    if entrada:
        st.session_state.historico_chat.append({"role": "user", "content": entrada})

        palavras_confirmacao = {
            "confirmo", "ok", "sim", "correto", "certo",
            "pode seguir", "confirmado", "tá bom", "ta bom"
        }
        if any(p in entrada.lower().strip() for p in palavras_confirmacao):
            estudo.etapa_atual = 2
            st.session_state.etapa1_confirmada = True
            resposta = (
                "✅ **Etapa 1 confirmada.** Iniciando análise do baseline...\n\n"
                f"- Categoria: {estudo.categoria}\n"
                f"- Modelo de precificação: {estudo.modelo_precificacao}\n"
                f"- Documentos: {len(estudo.documentos)}"
            )
        else:
            resposta = aplicar_correcao_etapa1(estudo, entrada)

        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

# -----------------------------------------------------------------------
# ETAPA 2 — análise do baseline
# -----------------------------------------------------------------------
if st.session_state.etapa1_confirmada and st.session_state.etapa2_resultado is None:
    resultado2 = rodar_etapa2(estudo)
    st.session_state.etapa2_resultado = resultado2
    st.session_state.historico_chat.append(
        {"role": "assistant", "content": resultado2["resumo"]}
    )

    # Se anualização precisar de confirmação, já pede
    if resultado2.get("precisa_confirmar_anualização"):
        msg_anualização = (
            "⚠️ **Preciso confirmar o período de anualização.** "
            "Informe aqui qual período usar (ex.: 'usar 12 meses', 'usar jan/2024 a dez/2024', etc.)."
        )
        st.session_state.historico_chat.append({"role": "assistant", "content": msg_anualização})
    else:
        st.session_state.etapa2_anualização_ok = True

    st.rerun()

# -----------------------------------------------------------------------
# ETAPA 2 — confirmação de anualização (se necessário)
# -----------------------------------------------------------------------
if (
    st.session_state.etapa2_resultado
    and not st.session_state.etapa2_anualização_ok
):
    entrada = st.chat_input("Informe o período de anualização...")
    if entrada:
        st.session_state.historico_chat.append({"role": "user", "content": entrada})
        resposta = confirmar_periodo_anualização(estudo, entrada)
        st.session_state.etapa2_anualização_ok = True
        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

# -----------------------------------------------------------------------
# RESUMO FINAL
# -----------------------------------------------------------------------
if st.session_state.etapa2_resultado and st.session_state.etapa2_anualização_ok:
    st.success("Etapas 1 e 2 concluídas. Pronto pra receber a Etapa 3.")

    with st.expander("Ver estado completo do Estudo"):
        st.write("**Categoria:**", estudo.categoria)
        st.write("**Micro-categoria:**", estudo.micro_categoria)
        st.write("**Modelo de precificação:**", estudo.modelo_precificacao)
        st.write("**Documentos classificados:**")
        for d in estudo.documentos:
            st.write(f"- {d['nome']} → `{d['tipo']}`")
        if estudo.premissas:
            st.write("**Premissas registradas:**")
            for p in estudo.premissas:
                st.write(f"- {p}")
        if estudo.faltantes:
            st.write("**Faltantes registrados:**")
            for f in estudo.faltantes:
                st.write(f"- {f}")
