"""
testar_etapa6.py — Entrypoint pra testar Etapas 1 a 6 em sequência.

Inclui a Etapa 4B (extração comercial das propostas), que não é uma das 8
etapas conceituais do v8, mas é pré-requisito de dados pra Etapa 6 rodar.

Rode com:
    streamlit run testar_etapa6.py
"""

import streamlit as st
from estudo import Estudo
from etapa1 import rodar_etapa1, aplicar_correcao_etapa1
from etapa2 import rodar_etapa2, confirmar_periodo_anualização
from etapa3 import rodar_etapa3
from etapa4 import rodar_etapa4
from etapa4b import rodar_etapa4b
from etapa5 import rodar_etapa5, gerar_word_etapa5, gerar_excel_etapa5
from etapa6 import rodar_etapa6, precisa_checkpoint_etapa6, confirmar_taxa_e_moeda

st.set_page_config(page_title="Etapas 1-6 — Teste", layout="wide")
st.title("Analisador de Propostas — Etapas 1 a 6")
st.caption(
    "Classificação → Baseline → Edital Técnico → Propostas Técnicas → "
    "Comparação Técnica → (Extração Comercial) → Equalização Comercial"
)

# --- Estado ---
defaults = {
    "estudo": Estudo(),
    "etapa1_resultado": None,
    "etapa1_confirmada": False,
    "etapa2_resultado": None,
    "etapa2_anualização_ok": False,
    "etapa3_resultado": None,
    "etapa4_resultado": None,
    "etapa4b_resultado": None,
    "etapa5_resultado": None,
    "etapa6_resultado": None,
    "etapa6_checkpoint_ok": False,
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
    bool(st.session_state.etapa5_resultado),
    bool(st.session_state.etapa4b_resultado),
    bool(st.session_state.etapa6_resultado),
])
st.progress(passo / 8, text=f"Passo {passo} de 8")

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
# ETAPA 5
# -----------------------------------------------------------------------
if st.session_state.etapa4_resultado and st.session_state.etapa5_resultado is None:
    resultado5 = rodar_etapa5(estudo)
    st.session_state.etapa5_resultado = resultado5
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado5["resumo"]})
    st.rerun()

# -----------------------------------------------------------------------
# ETAPA 4B — extração comercial (suporte à Etapa 6)
# -----------------------------------------------------------------------
if st.session_state.etapa5_resultado and st.session_state.etapa4b_resultado is None:
    resultado4b = rodar_etapa4b(estudo)
    st.session_state.etapa4b_resultado = resultado4b
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado4b["resumo"]})
    st.rerun()

# -----------------------------------------------------------------------
# CHECKPOINT ETAPA 6 — taxa de desconto e moeda (bloqueia até responder)
# -----------------------------------------------------------------------
if st.session_state.etapa4b_resultado and not st.session_state.etapa6_checkpoint_ok:
    if precisa_checkpoint_etapa6(estudo):
        if not any("taxa de desconto" in m["content"].lower() for m in st.session_state.historico_chat[-3:]):
            st.session_state.historico_chat.append({
                "role": "assistant",
                "content": (
                    "⚠️ **Preciso da taxa de desconto e da moeda de referência para equalizar.** "
                    "Informe no formato: `taxa: 8% | moeda: BRL`"
                )
            })
            st.rerun()
        entrada = st.chat_input("Ex.: taxa: 8% | moeda: BRL")
        if entrada:
            st.session_state.historico_chat.append({"role": "user", "content": entrada})
            try:
                partes = {p.split(":")[0].strip().lower(): p.split(":")[1].strip() for p in entrada.split("|")}
                taxa_str = partes.get("taxa", "0").replace("%", "").strip()
                taxa = float(taxa_str)
                moeda = partes.get("moeda", "BRL").upper()
                resposta = confirmar_taxa_e_moeda(estudo, taxa, moeda)
                st.session_state.etapa6_checkpoint_ok = True
            except (IndexError, ValueError):
                resposta = (
                    "Não entendi. Use o formato `taxa: 8% | moeda: BRL` "
                    "(taxa de desconto em % e código da moeda)."
                )
            st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
            st.rerun()
    else:
        st.session_state.etapa6_checkpoint_ok = True
        st.rerun()

# -----------------------------------------------------------------------
# ETAPA 6
# -----------------------------------------------------------------------
if st.session_state.etapa6_checkpoint_ok and st.session_state.etapa6_resultado is None:
    resultado6 = rodar_etapa6(estudo)
    st.session_state.etapa6_resultado = resultado6
    st.session_state.historico_chat.append({"role": "assistant", "content": resultado6["resumo"]})
    st.rerun()

# -----------------------------------------------------------------------
# RESUMO FINAL + DOWNLOADS DA ETAPA 5
# -----------------------------------------------------------------------
if st.session_state.etapa6_resultado:
    st.success("Etapas 1 a 6 concluídas.")

    if st.session_state.etapa5_resultado and st.session_state.etapa5_resultado.get("tem_dados"):
        st.subheader("📄 Exportar Comparação Técnica (Etapa 5)")
        col1, col2 = st.columns(2)
        with col1:
            word_buffer = gerar_word_etapa5(estudo)
            st.download_button(
                label="⬇️ Baixar Word (one-pager)",
                data=word_buffer,
                file_name="Comparacao_Tecnica.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            excel_buffer = gerar_excel_etapa5(estudo)
            st.download_button(
                label="⬇️ Baixar Excel (matriz detalhada)",
                data=excel_buffer,
                file_name="Comparacao_Tecnica.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    st.info("Etapa 6 ainda não tem saída formatada (Word/Excel) — fica para etapa posterior. Veja o resultado estruturado abaixo.")

    with st.expander("Ver estado do Estudo"):
        st.write("**Categoria:**", estudo.categoria)
        st.write("**Micro-categoria:**", estudo.micro_categoria)
        st.write("**Modelo de precificação (Etapa 1):**", estudo.modelo_precificacao)
        st.write("**Taxa de desconto:**", estudo.taxa_desconto)
        st.write("**Moeda de referência:**", estudo.regra_moeda)
        st.write(f"**Propostas técnicas avaliadas:** {len(estudo.propostas_tecnicas)}")
        st.write(f"**Propostas comerciais extraídas:** {len(estudo.propostas_comerciais)}")
        if estudo.equalizacao_comercial:
            st.json(estudo.equalizacao_comercial)
        if estudo.premissas:
            st.write("**Premissas:**")
            for p in estudo.premissas:
                st.write(f"- {p}")
        if estudo.faltantes:
            st.write("**Faltantes:**")
            for f in estudo.faltantes:
                st.write(f"- {f}")
