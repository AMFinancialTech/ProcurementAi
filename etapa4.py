"""
etapa4.py — Etapa 4: Análise das Propostas Técnicas.

O que faz:
1. Pega cada proposta classificada na Etapa 1 (tipo == "proposta").
2. Avalia cada uma, UMA POR VEZ (uma chamada de IA por fornecedor — é o que
   aguenta 6+ propostas sem o JSON truncar), contra a referência disponível:
      - edital (Etapa 3), se houver;
      - senão, o baseline (Etapa 2);
      - senão, extrai o escopo de cada proposta e registra a ressalva.
3. Para cada fornecedor produz: status por requisito (cumpre / não cumpre /
   parcial / desvio), distinção mandatório x desejável, inclusões/exclusões de
   escopo (elo com a Etapa 6), desvios lidos como gap ou oportunidade, e a flag
   "não cumpre mandatório" (candidato a janela de flexibilização na Etapa 6).
4. NÃO elimina o não-conforme — apenas marca.
5. Grava tudo no Estudo (propostas_tecnicas) e monta a matriz de conformidade.
"""

import json
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude

MAX_TOKENS_ETAPA4 = 8000


# ---------------------------------------------------------------------------
# Prompt (avalia UMA proposta por vez)
# ---------------------------------------------------------------------------

SYSTEM_PROPOSTA = """
Você é um especialista sênior em procurement avaliando a ÓTICA TÉCNICA de UMA
proposta de fornecedor. Foco em escopo e aderência — NÃO faça análise de preço
aqui (isso é outra etapa).

Você recebe: o modo de referência, a referência em si (requisitos do edital, ou
o escopo do baseline, ou nada), e o texto da proposta.

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois:

{
  "fornecedor": "<nome do fornecedor, se identificável; senão o nome do arquivo>",
  "resumo_tecnico": "<2-3 frases sobre a aderência geral desta proposta>",
  "conformidade": [
    {
      "req_id": "<id do requisito do edital (ex. R01); '—' se não houver edital>",
      "descricao_curta": "<requisito ou elemento de escopo avaliado>",
      "tipo": "mandatório|desejável|—",
      "status": "cumpre|não cumpre|parcial|desvio",
      "observacao": "<evidência ou justificativa curta>"
    }
  ],
  "desvios": [
    {
      "descricao": "<o que o fornecedor ofereceu no lugar do que foi pedido>",
      "leitura": "gap|oportunidade",
      "observacao": "<por que é gap ou por que pode ser oportunidade>"
    }
  ],
  "inclusoes_escopo": [
    "<item/serviço que ESTE fornecedor inclui e que pode não estar nos outros>"
  ],
  "exclusoes_escopo": [
    "<item/serviço que ESTE fornecedor deixou de fora do escopo>"
  ],
  "nao_cumpre_mandatorio": <true|false>,
  "mandatorios_nao_cumpridos": [
    "<req_id: descrição curta do mandatório não cumprido>"
  ],
  "premissas": ["<premissa assumida na avaliação desta proposta>"],
  "faltantes": ["<informação que faltou nesta proposta>"]
}

Regras:
- MODO "edital": avalie a proposta requisito a requisito, usando os req_id dados.
  status: cumpre / não cumpre / parcial (atende em parte) / desvio (oferece
  alternativa ao que foi pedido).
- MODO "baseline": não há requisitos formais — avalie a proposta contra o escopo
  atual descrito no baseline. Use req_id "—" e descreva o elemento de escopo.
- MODO "entre_si": não há referência — apenas EXTRAIA o escopo/specs que esta
  proposta oferece (conformidade pode ficar vazia), capriche em inclusoes_escopo
  e exclusoes_escopo, e registre em 'faltantes' que não havia referência.
- NÃO elimine o fornecedor por não cumprir mandatório. Apenas marque
  nao_cumpre_mandatorio=true e liste em mandatorios_nao_cumpridos.
- 'desvio' não é automaticamente ruim: se a alternativa do fornecedor pode ser
  mais barata/melhor, marque leitura="oportunidade".
- LIMITE DE TAMANHO: conformidade máximo 30 itens; desvios máximo 10;
  inclusoes_escopo e exclusoes_escopo máximo 8 cada; mandatorios_nao_cumpridos
  máximo 10; premissas e faltantes máximo 5 cada.
  O JSON completo deve caber em 6000 tokens.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _propostas(estudo) -> list:
    """Documentos classificados como proposta."""
    return [d for d in estudo.documentos if d.get("tipo") == "proposta"]


def _resolver_referencia(estudo):
    """
    Decide contra o que comparar as propostas e monta o texto de referência.
    Retorna (modo, texto_referencia).
    """
    requisitos = (estudo.edital or {}).get("requisitos", [])
    if requisitos:
        linhas = ["REQUISITOS DO EDITAL:"]
        for r in requisitos:
            linhas.append(
                f"- [{r.get('id','?')}] ({r.get('tipo','?')}, peso {r.get('peso','?')}) "
                f"{r.get('descricao','')}"
            )
        return "edital", "\n".join(linhas)

    if estudo.baseline:
        tec = estudo.baseline.get("tecnica", {})
        texto = (
            "ESCOPO ATUAL (BASELINE) — usar como referência, pois não há edital:\n"
            f"{tec.get('escopo_atual', '—')}"
        )
        return "baseline", texto

    return "entre_si", "Não há edital nem baseline. Extraia o escopo da proposta."


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
                "Proposta muito extensa — verifique o arquivo."
            )


def _avaliar_proposta(estudo, doc, modo, texto_ref) -> dict:
    """Roda uma chamada de IA para UMA proposta."""
    contexto = (
        f"MODO DE REFERÊNCIA: {modo}\n"
        f"Categoria: {estudo.categoria} | Modelo: {estudo.modelo_precificacao} | "
        f"Micro-categoria: {estudo.micro_categoria or '—'}\n\n"
        f"{texto_ref}\n\n"
        f"=== PROPOSTA: {doc['nome']} ===\n{_texto_proposta(doc)}"
    )
    resposta_bruta = call_claude(
        messages=[{"role": "user", "content": contexto}],
        system=SYSTEM_PROPOSTA,
        max_tokens=MAX_TOKENS_ETAPA4,
    )
    analise = _parse_resposta(resposta_bruta)
    # Garante um nome de fornecedor utilizável
    if not analise.get("fornecedor"):
        analise["fornecedor"] = doc["nome"]
    analise["_arquivo"] = doc["nome"]
    return analise


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa4(estudo) -> dict:
    """
    Executa a Etapa 4 completa.

    Retorna dict com:
        - n_propostas : int
        - analises    : list (uma por fornecedor) — também gravado em estudo.propostas_tecnicas
        - resumo      : texto legível pra UI
    """
    propostas = _propostas(estudo)

    if not propostas:
        msg = "Nenhuma proposta identificada — Etapa 4 não pôde rodar."
        estudo.add_faltante(msg)
        return {"n_propostas": 0, "analises": [], "resumo": f"⚠️ {msg}"}

    modo, texto_ref = _resolver_referencia(estudo)
    if modo == "entre_si":
        estudo.add_faltante(
            "Sem edital e sem baseline: propostas avaliadas apenas pelo escopo "
            "que cada uma declara, sem checagem formal de conformidade."
        )

    analises = []
    for doc in propostas:
        with st.spinner(f"Etapa 4 — avaliando proposta: {doc['nome']}..."):
            try:
                analise = _avaliar_proposta(estudo, doc, modo, texto_ref)
            except (json.JSONDecodeError, ValueError) as e:
                st.warning(f"Falha ao avaliar '{doc['nome']}': {e}. Proposta registrada como não analisada.")
                estudo.add_faltante(f"Proposta '{doc['nome']}' não pôde ser analisada (erro de parsing).")
                continue
        analises.append(analise)
        for p in analise.get("premissas", []):
            estudo.add_premissa(f"[{analise['fornecedor']}] {p}")
        for f in analise.get("faltantes", []):
            estudo.add_faltante(f"[{analise['fornecedor']}] {f}")
        if analise.get("nao_cumpre_mandatorio"):
            estudo.add_premissa(
                f"[{analise['fornecedor']}] não cumpre mandatório(s) "
                f"{', '.join(analise.get('mandatorios_nao_cumpridos', [])) or '(ver detalhe)'} "
                f"— candidato a janela de flexibilização (custear na Etapa 6)."
            )

    estudo.propostas_tecnicas = analises
    estudo.etapa_atual = 4

    resumo = _montar_resumo(modo, analises)
    return {"n_propostas": len(analises), "analises": analises, "resumo": resumo}


# ---------------------------------------------------------------------------
# Resumo legível
# ---------------------------------------------------------------------------

def _montar_resumo(modo, analises) -> str:
    if not analises:
        return "Nenhuma proposta analisada."

    linhas = [f"**Propostas técnicas analisadas:** {len(analises)} (modo de referência: {modo})"]

    # Flags transversais primeiro (é o que mais importa pro consultor)
    nao_conformes = [a for a in analises if a.get("nao_cumpre_mandatorio")]
    if nao_conformes:
        linhas.append("\n**⚠️ Não cumprem requisito mandatório (NÃO eliminados — janela de flexibilização p/ Etapa 6):**")
        for a in nao_conformes:
            mnc = ", ".join(a.get("mandatorios_nao_cumpridos", [])) or "(ver detalhe)"
            linhas.append(f"- **{a['fornecedor']}**: {mnc}")

    # Por fornecedor
    for a in analises:
        linhas.append(f"\n---\n### {a['fornecedor']}")
        if a.get("resumo_tecnico"):
            linhas.append(a["resumo_tecnico"])

        conf = a.get("conformidade", [])
        if conf:
            n_cumpre = sum(1 for c in conf if c.get("status") == "cumpre")
            n_parcial = sum(1 for c in conf if c.get("status") == "parcial")
            n_nao = sum(1 for c in conf if c.get("status") == "não cumpre")
            n_desvio = sum(1 for c in conf if c.get("status") == "desvio")
            linhas.append(
                f"\n_Conformidade:_ {n_cumpre} cumpre · {n_parcial} parcial · "
                f"{n_nao} não cumpre · {n_desvio} desvio"
            )

        incl = a.get("inclusoes_escopo", [])
        if incl:
            linhas.append("\n**Inclui no escopo (atenção p/ equalização):**")
            for i in incl:
                linhas.append(f"- {i}")
        excl = a.get("exclusoes_escopo", [])
        if excl:
            linhas.append("\n**Exclui do escopo:**")
            for e in excl:
                linhas.append(f"- {e}")

        oportunidades = [d for d in a.get("desvios", []) if d.get("leitura") == "oportunidade"]
        if oportunidades:
            linhas.append("\n**Desvios que podem ser oportunidade:**")
            for d in oportunidades:
                linhas.append(f"- {d.get('descricao','')} — {d.get('observacao','')}")

    return "\n".join(linhas)
