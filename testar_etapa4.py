"""
testar_etapa4.py — Entrypoint pra testar Etapas 1, 2, 3 e 4 em sequência.

Rode com:
    streamlit run testar_etapa4.py
"""

import streamlit as st
from estudo import Estudo
from etapa1 import rodar_etapa1, aplicar_correcao_etapa1
from etapa2 import rodar_etapa2, confirmar_periodo_anualização
from etapa3 import rodar_etapa3
from etapa4 import rodar_etapa4

st.set_page_config(page_title="Etapas 1-4 — Teste", layout="wide")
st.title("Analisador de Propostas — Etapas 1 a 4")
st.caption("Classificação → Baseline → Edital Técnico → Propostas Técnicas")

# --- Estado ---
defaults = {
    "estudo": Estudo(),
    "etapa1_resultado": None,
    "etapa1_confirmada": False,
    "etapa2_resultado": None,
    "etapa2_anualização_ok": False,
    "etapa3_resultado": None,
    "etapa4_resultado": None,
    "historico_chat": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

estudo = st.session_state.estudo

# --- Progresso ---
passo = sum([
    bool(st.session_state.etapa1_resultado),
    bool(st.session_state.etapa1_confirmada),
    bool(st.session_state.etapa2_resultado and st.session_state.etapa2_anualização_ok),
    bool(st.session_state.etapa3_resultado),
    bool(st.session_state.etapa4_resultado),
])
st.progress(passo / 5, text=f"Passo {passo} de 5")

# -----------------------------------------------------------------------
# UPLOAD + ETAPA 1
# -----------------------------------------------------------------------
if not st.session_state.etapa1_confirmada:
    arquivos = st.file_uploader(
        "Suba os arquivos (edital, propostas, baseline...)",
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

# --- Histórico ---
for msg in st.session_state.historico_chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Checkpoint Etapa 1 ---
if st.session_state.etapa1_resultado and not st.session_state.etapa1_confirmada:
    entrada = st.chat_input("Confirme a classificação ou corrija aqui...")
    if entrada:
        st.session_state.historico_chat.append({"role": "user", "content": entrada})
        palavras_ok = {"confirmo","ok","sim","correto","certo","pode seguir","confirmado","tá bom","ta bom"}
        if any(p in entrada.lower() for p in palavras_ok):
            st.session_state.etapa1_confirmada = True
            estudo.etapa_atual = 2
            resposta = (
                f"✅ **Etapa 1 confirmada.** Iniciando análise do baseline...\n\n"
                f"- Categoria: {estudo.categoria}\n"
                f"- Modelo: {estudo.modelo_precificacao}\n"
                f"- Documentos: {len(estudo.documentos)}"
            )
        else:
            resposta = aplicar_correcao_etapa1(estudo, entrada)
        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

# -----------------------------------------------------------------------
# ETAPA 2
# -----------------------------------------------------------------------
if st.session_state.etapa1_confirmada and st.session_state.etapa2_resultado is None:
    resultado2 = rodar_etapa2(estudo)
    st.session_state.etapa2_resultado = resultado2
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado2["resumo"]})
    if resultado2.get("precisa_confirmar_anualização"):
        st.session_state.historico_chat.append({
            "role": "assistant",
            "content": "⚠️ **Preciso confirmar o período de anualização.** Informe aqui qual período usar."
        })
    else:
        st.session_state.etapa2_anualização_ok = True
    st.rerun()

if st.session_state.etapa2_resultado and not st.session_state.etapa2_anualização_ok:
    entrada = st.chat_input("Informe o período de anualização...")
    if entrada:
        st.session_state.historico_chat.append({"role": "user", "content": entrada})
        resposta = confirmar_periodo_anualização(estudo, entrada)
        st.session_state.etapa2_anualização_ok = True
        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

# -----------------------------------------------------------------------
# ETAPA 3
# -----------------------------------------------------------------------
if (
    st.session_state.etapa2_resultado
    and st.session_state.etapa2_anualização_ok
    and st.session_state.etapa3_resultado is None
):
    resultado3 = rodar_etapa3(estudo)
    st.session_state.etapa3_resultado = resultado3
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado3["resumo"]})
    st.rerun()

# -----------------------------------------------------------------------
# ETAPA 4
# -----------------------------------------------------------------------
if st.session_state.etapa3_resultado and st.session_state.etapa4_resultado is None:
    resultado4 = rodar_etapa4(estudo)
    st.session_state.etapa4_resultado = resultado4
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado4["resumo"]})
    st.rerun()

# -----------------------------------------------------------------------
# RESUMO FINAL
# -----------------------------------------------------------------------
if st.session_state.etapa4_resultado:
    st.success("Etapas 1 a 4 concluídas. Pronto pra Etapa 5.")

    with st.expander("Ver estado do Estudo"):
        st.write("**Categoria:**", estudo.categoria)
        st.write("**Micro-categoria:**", estudo.micro_categoria)
        st.write("**Modelo:**", estudo.modelo_precificacao)
        req = (estudo.edital or {}).get("requisitos", [])
        st.write(f"**Requisitos extraídos:** {len(req)}")
        st.write(f"**Propostas técnicas avaliadas:** {len(estudo.propostas_tecnicas)}")
        for a in estudo.propostas_tecnicas:
            flag = " ⚠️ não cumpre mandatório" if a.get("nao_cumpre_mandatorio") else ""
            st.write(f"- {a.get('fornecedor','?')}{flag}")
        if estudo.premissas:
            st.write("**Premissas:**")
            for p in estudo.premissas:
                st.write(f"- {p}")
        if estudo.faltantes:
            st.write("**Faltantes:**")
            for f in estudo.faltantes:
                st.write(f"- {f}")
