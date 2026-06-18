"""
etapa3.py — Etapa 3: Análise do Edital Técnico.

O que faz:
1. Verifica se há edital no Estudo (classificado na Etapa 1).
   Se não houver, registra premissa e encerra — as etapas seguintes
   usarão o baseline ou as propostas entre si como referência.
2. Extrai os requisitos do edital, classificando cada um como
   mandatório ou desejável, com peso (Alto/Médio/Baixo).
3. Compara o edital com o baseline (se existir) e lista o delta de
   escopo: o que foi adicionado, o que foi removido, o que mudou.
   Esse delta é o que justifica variações de preço nas propostas.
4. Grava tudo no objeto Estudo para uso nas Etapas 4 e 6.
"""

import json
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_EDITAL = """
Você é um especialista sênior em procurement e análise de editais/RFPs.
Vai receber o conteúdo de um edital (ou memorial descritivo / termos de
referência) e, quando disponível, o resumo do baseline (cenário atual).

Sua tarefa é:
1. Extrair todos os requisitos do edital.
2. Comparar com o baseline e identificar o delta de escopo.

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois:

{
  "resumo_edital": "<1-2 frases: o que está sendo contratado, prazo, escopo geral>",
  "requisitos": [
    {
      "id": "R01",
      "categoria": "<categoria do requisito: ex. Técnico | Comercial | Jurídico | SLA | Ambiental>",
      "descricao": "<descrição clara do requisito>",
      "tipo": "mandatório|desejável",
      "peso": "Alto|Médio|Baixo",
      "justificativa_peso": "<por que esse peso>"
    }
  ],
  "delta_escopo": {
    "tem_baseline": <true|false>,
    "adicionados": [
      {"item": "<o que foi adicionado vs baseline>", "impacto_custo": "alta|média|baixa|desconhecido"}
    ],
    "removidos": [
      {"item": "<o que foi removido vs baseline>", "impacto_custo": "alta|média|baixa|desconhecido"}
    ],
    "modificados": [
      {"item": "<o que mudou>", "antes": "<como era>", "depois": "<como ficou>", "impacto_custo": "alta|média|baixa|desconhecido"}
    ],
    "narrativa_delta": "<parágrafo explicando as mudanças principais e por que elas afetam o preço>"
  },
  "premissas_registradas": [
    "<premissa assumida na análise>"
  ],
  "faltantes": [
    "<informação que faltou no edital e pode impactar a análise>"
  ]
}

Regras:
- Requisitos: extraia todos, sem omitir. Classifique como mandatório tudo
  que use linguagem imperativa (deverá, deve, é obrigatório, exige-se).
  Desejável para linguagem condicional (poderá, preferencialmente, é
  desejável).
- Peso: Alto = impacto direto na operação ou risco de desclassificação;
  Médio = relevante mas não crítico; Baixo = complementar.
- Delta: só preencha adicionados/removidos/modificados se houver baseline.
  Se não houver, marque tem_baseline=false e deixe as listas vazias.
- LIMITE DE TAMANHO: requisitos máximo 30 itens (agrupe os muito similares);
  adicionados/removidos/modificados máximo 10 itens cada;
  premissas e faltantes máximo 5 itens cada.
  O JSON completo deve caber em 6000 tokens.
"""


def _texto_edital(estudo) -> str:
    """Extrai o texto dos documentos classificados como edital."""
    partes = []
    for doc in estudo.documentos:
        if doc.get("tipo") == "edital":
            texto = doc.get("texto", "")[:MAX_CHARS_PER_DOC]
            partes.append(f"=== EDITAL: {doc['nome']} ===\n{texto}")
    return "\n\n".join(partes)


def _resumo_baseline(estudo) -> str:
    """Monta um resumo compacto do baseline para o contexto do prompt."""
    if not estudo.baseline:
        return "Baseline: não disponível."
    tec = estudo.baseline.get("tecnica", {})
    com = estudo.baseline.get("comercial", {})
    return (
        f"Baseline disponível.\n"
        f"Escopo atual: {tec.get('escopo_atual', '—')}\n"
        f"Gasto anual atual: R$ {com.get('preco_anual_total') or '—'}\n"
        f"Micro-categoria: {estudo.micro_categoria or '—'}"
    )


def _parse_resposta(resposta_bruta: str) -> dict:
    texto = resposta_bruta.strip()
    if texto.startswith("```"):
        linhas = texto.split("\n")
        texto = "\n".join(linhas[1:-1]).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        texto_cortado = texto.rstrip().rstrip(",")
        abertas = texto_cortado.count("{") - texto_cortado.count("}")
        colchetes = texto_cortado.count("[") - texto_cortado.count("]")
        fechamento = "]" * colchetes + "}" * abertas
        try:
            return json.loads(texto_cortado + fechamento)
        except json.JSONDecodeError:
            raise ValueError(
                "JSON inválido mesmo após tentativa de correção. "
                "Edital muito extenso — verifique o arquivo."
            )


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa3(estudo) -> dict:
    """
    Executa a Etapa 3 completa.

    Parâmetros
    ----------
    estudo : objeto Estudo — já populado pelas Etapas 1 e 2.

    Retorna
    -------
    resultado : dict com:
        - tem_edital  : bool
        - analise     : dict completo (JSON do Claude) ou None
        - resumo      : texto legível pra exibir na UI
    """

    # 1. Verificar se há edital
    tipos = {d.get("tipo") for d in estudo.documentos}
    if "edital" not in tipos:
        msg = (
            "Edital não identificado — Etapa 3 pulada. "
            "A Etapa 4 comparará as propostas entre si e contra o baseline (se disponível)."
        )
        estudo.add_faltante(msg)
        # Grava edital vazio no Estudo para as etapas seguintes saberem
        estudo.edital = {"requisitos": [], "delta_escopo": {"tem_baseline": False}}
        return {
            "tem_edital": False,
            "analise": None,
            "resumo": f"⚠️ {msg}",
        }

    # 2. Montar mensagem
    texto_edital = _texto_edital(estudo)
    resumo_bl = _resumo_baseline(estudo)
    contexto = (
        f"Categoria: {estudo.categoria}\n"
        f"Modelo de precificação: {estudo.modelo_precificacao}\n"
        f"Micro-categoria: {estudo.micro_categoria or '—'}\n\n"
        f"{resumo_bl}\n\n"
        f"{texto_edital}"
    )

    # 3. Chamar Claude
    with st.spinner("Etapa 3 — analisando edital técnico..."):
        resposta_bruta = call_claude(
            messages=[{"role": "user", "content": contexto}],
            system=SYSTEM_EDITAL,
            max_tokens=6000,
        )

    # 4. Parsear
    try:
        analise = _parse_resposta(resposta_bruta)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Erro ao interpretar resposta da IA na Etapa 3: {e}\n\nResposta bruta:\n{resposta_bruta}")
        st.stop()

    # 5. Gravar no Estudo
    estudo.edital = analise

    for p in analise.get("premissas_registradas", []):
        estudo.add_premissa(p)
    for f in analise.get("faltantes", []):
        estudo.add_faltante(f)

    estudo.etapa_atual = 3

    # 6. Montar resumo
    resumo = _montar_resumo(analise)

    return {
        "tem_edital": True,
        "analise": analise,
        "resumo": resumo,
    }


def _montar_resumo(analise: dict) -> str:
    linhas = []

    resumo_edital = analise.get("resumo_edital")
    if resumo_edital:
        linhas.append(f"**Edital:** {resumo_edital}")

    # Requisitos
    requisitos = analise.get("requisitos", [])
    mandatorios = [r for r in requisitos if r.get("tipo") == "mandatório"]
    desejaveis = [r for r in requisitos if r.get("tipo") == "desejável"]

    linhas.append(f"\n**Requisitos extraídos:** {len(requisitos)} total "
                  f"({len(mandatorios)} mandatórios, {len(desejaveis)} desejáveis)")

    # Mandatórios de peso Alto
    altos = [r for r in mandatorios if r.get("peso") == "Alto"]
    if altos:
        linhas.append("\n**Mandatórios críticos (peso Alto):**")
        for r in altos:
            linhas.append(f"- [{r.get('id','?')}] {r.get('descricao','')}")

    # Delta de escopo
    delta = analise.get("delta_escopo", {})
    if delta.get("tem_baseline"):
        narrativa = delta.get("narrativa_delta")
        if narrativa:
            linhas.append(f"\n**Delta vs baseline:** {narrativa}")

        adicionados = delta.get("adicionados", [])
        removidos = delta.get("removidos", [])
        modificados = delta.get("modificados", [])

        if adicionados:
            linhas.append("\n**Adicionados no edital (vs baseline):**")
            for a in adicionados:
                linhas.append(f"- {a.get('item','')} _(impacto de custo: {a.get('impacto_custo','?')})_")
        if removidos:
            linhas.append("\n**Removidos do escopo (vs baseline):**")
            for r in removidos:
                linhas.append(f"- {r.get('item','')} _(impacto de custo: {r.get('impacto_custo','?')})_")
        if modificados:
            linhas.append("\n**Modificados (vs baseline):**")
            for m in modificados:
                linhas.append(f"- {m.get('item','')}: {m.get('antes','?')} → {m.get('depois','?')} "
                              f"_(impacto: {m.get('impacto_custo','?')})_")
    else:
        linhas.append("\n_Sem baseline disponível — delta de escopo não calculado._")

    # Premissas
    premissas = analise.get("premissas_registradas", [])
    if premissas:
        linhas.append("\n**Premissas assumidas:**")
        for p in premissas:
            linhas.append(f"- {p}")

    return "\n".join(linhas)
