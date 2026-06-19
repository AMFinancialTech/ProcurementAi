"""
etapa4b.py — Extração Comercial das Propostas (suporte à Etapa 6).

Não é uma das 8 etapas conceituais do projeto — é um módulo de apoio.
A Etapa 4 (técnica) deliberadamente NÃO extrai preço, por design do v8:
"Separar a ótica TÉCNICA da COMERCIAL, analisar isoladamente, e só depois
correlacionar." Esta extração comercial é o que falta pra Etapa 6 ter
dados de onde partir.

O que faz:
1. Pega as mesmas propostas que a Etapa 4 já filtrou — tipos
   {proposta_combinada, proposta_comercial} (proposta_tecnica não tem preço
   por definição, então fica de fora aqui).
2. Avalia cada uma, UMA POR VEZ (mesmo padrão da Etapa 4), extraindo SÓ os
   dados comerciais: itens precificados, preço total, moeda, condições de
   pagamento, reajuste, impostos/frete inclusos, validade.
3. NÃO compara nem equaliza nada — isso é trabalho da Etapa 6. Aqui é só
   extração fiel do que está escrito na proposta.
4. Grava em estudo.propostas_comerciais (uma entrada por fornecedor).
"""

import json
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude

MAX_TOKENS_ETAPA4B = 8000

# Mesmos tipos que a Etapa 4 usa para propostas, exceto proposta_tecnica
# (que por definição não carrega preço).
TIPOS_PROPOSTA_COMERCIAL = {"proposta_combinada", "proposta_comercial"}


# ---------------------------------------------------------------------------
# Prompt (extrai UMA proposta comercial por vez)
# ---------------------------------------------------------------------------

SYSTEM_COMERCIAL = """
Você é um especialista sênior em procurement extraindo os DADOS COMERCIAIS de
UMA proposta de fornecedor. Esta é extração fiel, não análise nem comparação
— não julgue se o preço é bom ou ruim, não compare com outras propostas.

Você recebe o modelo de precificação detectado para esta categoria (pode
servir de guia, mas confie no que a proposta realmente diz) e o texto da
proposta.

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois:

{
  "fornecedor": "<nome do fornecedor, se identificável; senão o nome do arquivo>",
  "modelo_precificacao_ofertado": "<hora-homem|por_funcionario|mensal_fixo|variavel_por_consumo|tpq|misto|desconhecido — o que a PROPOSTA realmente usa, pode diferir do detectado na Etapa 1>",
  "moeda": "<BRL|USD|EUR|... — moeda em que os valores estão expressos>",
  "itens_precificados": [
    {"item": "<descrição>", "valor_unitario": <número ou null>, "unidade": "<ex.: hora, mês, unidade, posto>", "quantidade": <número ou null>}
  ],
  "preco_total_proposto": <número em moeda da proposta, anualizado quando possível; null se não for possível calcular>,
  "base_anualizacao": "<como chegou ao valor anualizado: vigência, mensal x12, etc.; ou '—' se preco_total_proposto for null>",
  "condicoes_pagamento": "<ex.: 30 dias, antecipado, etc.; '—' se não informado>",
  "reajuste": "<índice e periodicidade de reajuste, se informado; '—' se não informado>",
  "impostos_inclusos": "sim|não|não informado",
  "frete_incluso": "sim|não|não informado|n/a",
  "validade_proposta": "<prazo de validade da proposta, se informado; '—' se não informado>",
  "premissas": ["<premissa assumida nesta extração>"],
  "faltantes": ["<dado comercial que faltou na proposta>"]
}

Regras:
- Extraia só o que está escrito. Não infira preço a partir do que seria
  "razoável" para a categoria — isso é trabalho de outra etapa.
- Se a proposta não permitir calcular um total anualizado (ex.: só lista
  valores unitários sem indicar volume), deixe preco_total_proposto null e
  explique em faltantes.
- Se houver múltiplas moedas na mesma proposta, registre a moeda predominante
  do preço total e use faltantes para sinalizar o detalhe.
- LIMITE DE TAMANHO: itens_precificados máximo 20 itens (agrupe itens muito
  similares); premissas e faltantes máximo 5 itens cada.
  O JSON completo deve caber em 6000 tokens.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _propostas_comerciais(estudo) -> list:
    """Documentos classificados como proposta com dado comercial (combinada ou comercial)."""
    return [d for d in estudo.documentos if d.get("tipo") in TIPOS_PROPOSTA_COMERCIAL]


def _texto_proposta(doc) -> str:
    return doc.get("texto", "")[:MAX_CHARS_PER_DOC]


def _parse_resposta(resposta_bruta: str) -> dict:
    """Parser com fallback de truncamento (mesmo padrão das outras etapas)."""
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
                "Proposta comercial muito extensa — verifique o arquivo."
            )


def _extrair_comercial(estudo, doc) -> dict:
    """Roda uma chamada de IA para extrair os dados comerciais de UMA proposta."""
    contexto = (
        f"Categoria: {estudo.categoria} | "
        f"Modelo de precificação detectado (Etapa 1): {estudo.modelo_precificacao} | "
        f"Micro-categoria: {estudo.micro_categoria or '—'}\n\n"
        f"=== PROPOSTA: {doc['nome']} ===\n{_texto_proposta(doc)}"
    )
    resposta_bruta = call_claude(
        messages=[{"role": "user", "content": contexto}],
        system=SYSTEM_COMERCIAL,
        max_tokens=MAX_TOKENS_ETAPA4B,
    )
    analise = _parse_resposta(resposta_bruta)
    if not analise.get("fornecedor"):
        analise["fornecedor"] = doc["nome"]
    analise["_arquivo"] = doc["nome"]
    return analise


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa4b(estudo) -> dict:
    """
    Executa a extração comercial completa.

    Retorna dict com:
        - n_propostas : int
        - analises    : list (uma por fornecedor) — também gravado em estudo.propostas_comerciais
        - resumo      : texto legível pra UI
    """
    propostas = _propostas_comerciais(estudo)

    if not propostas:
        msg = (
            "Nenhuma proposta com dado comercial identificada — extração comercial "
            "não pôde rodar. Etapa 6 não terá preço de proposta para equalizar."
        )
        estudo.add_faltante(msg)
        estudo.propostas_comerciais = []
        return {"n_propostas": 0, "analises": [], "resumo": f"⚠️ {msg}"}

    analises = []
    for doc in propostas:
        with st.spinner(f"Extraindo dados comerciais: {doc['nome']}..."):
            try:
                analise = _extrair_comercial(estudo, doc)
            except (json.JSONDecodeError, ValueError) as e:
                st.warning(f"Falha ao extrair dados comerciais de '{doc['nome']}': {e}. Proposta registrada como não extraída.")
                estudo.add_faltante(f"Proposta '{doc['nome']}' não pôde ter dados comerciais extraídos (erro de parsing).")
                continue
        analises.append(analise)
        for p in analise.get("premissas", []):
            estudo.add_premissa(f"[{analise['fornecedor']}] {p}")
        for f in analise.get("faltantes", []):
            estudo.add_faltante(f"[{analise['fornecedor']}] {f}")
        if analise.get("preco_total_proposto") is None:
            estudo.add_faltante(
                f"[{analise['fornecedor']}] preço total anualizado não pôde ser calculado "
                f"a partir da proposta — Etapa 6 vai precisar de premissa adicional."
            )

    estudo.propostas_comerciais = analises

    resumo = _montar_resumo(analises)
    return {"n_propostas": len(analises), "analises": analises, "resumo": resumo}


def _montar_resumo(analises: list) -> str:
    if not analises:
        return "Nenhuma proposta comercial extraída."

    linhas = [f"**Propostas comerciais extraídas:** {len(analises)}"]

    for a in analises:
        linhas.append(f"\n---\n### {a.get('fornecedor','?')}")
        preco = a.get("preco_total_proposto")
        moeda = a.get("moeda", "—")
        if preco is not None:
            linhas.append(f"**Preço total proposto:** {moeda} {preco:,.2f}")
            linhas.append(f"_Base de anualização: {a.get('base_anualizacao','—')}_")
        else:
            linhas.append("**Preço total proposto:** não foi possível calcular.")
        linhas.append(f"**Modelo de precificação ofertado:** {a.get('modelo_precificacao_ofertado','—')}")
        linhas.append(
            f"Impostos inclusos: {a.get('impostos_inclusos','—')} · "
            f"Frete incluso: {a.get('frete_incluso','—')} · "
            f"Condições de pagamento: {a.get('condicoes_pagamento','—')}"
        )

        itens = a.get("itens_precificados", [])
        if itens:
            linhas.append(f"\n_Itens precificados:_ {len(itens)} item(ns)")

    return "\n".join(linhas)
