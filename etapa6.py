"""
etapa6.py — Etapa 6: Equalização Comercial.

A mais pesada e valiosa do modelo de 8 etapas (definição do v8).

O que faz:
1. CHECKPOINT antes de chamar a IA: pergunta taxa de desconto e moeda de
   referência via chatbox (mesmo padrão da anualização na Etapa 2). Sem
   essas duas respostas, a equalização não roda — ficam gravadas em
   estudo.taxa_desconto e estudo.regra_moeda.
2. Normaliza a base comum: usa o modelo de precificação (Etapa 1) para
   decidir como tornar os preços comparáveis entre fornecedores e contra
   o baseline.
3. Ramifica pelo modelo de precificação:
   - hora-homem          → equaliza por taxa horária x volume de referência
   - por_funcionario     → equaliza por custo/posto x headcount de referência
   - mensal_fixo         → comparação direta (mensal x12), sem ramificação extra
   - variavel_por_consumo→ exige volume de referência do baseline; se não
                           houver, marca premissa e segue com o que a
                           proposta declarou
   - tpq                 → equaliza item a item (valores unitários)
   - misto               → trata cada componente conforme seu próprio modelo
4. Isola on-tops (NÃO mistura no preço base):
   - on-top de escopo: vem do delta_escopo da Etapa 3 (itens adicionados/
     removidos/modificados no edital vs baseline)
   - on-top de desvio/inclusão/exclusão: vem das inclusões/exclusões de
     escopo e do flag nao_cumpre_mandatorio da Etapa 4 (proposta inclui algo
     que as outras não, ou não cumpre um mandatório — isso tem valor/custo
     que precisa ficar rastreável separadamente)
5. Aplica ajustes de frete/impostos/prazo/moeda quando a 4B sinalizar que
   não estão inclusos, usando a taxa_desconto e regra_moeda informadas.
6. Saída: preço equalizado por fornecedor + savings vs baseline. Grava em
   estudo.equalizacao_comercial. SEM saída formatada (Word/Excel) ainda —
   fica para etapa posterior.
"""

import json
import streamlit as st

from ia import call_claude

MAX_TOKENS_ETAPA6 = 8000


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_EQUALIZACAO = """
Você é um especialista sênior em procurement produzindo a EQUALIZAÇÃO
COMERCIAL de um estudo de propostas. Você recebe dados já extraídos por
outras etapas (não releia documento bruto): preço atual (baseline), dados
comerciais de cada proposta, delta de escopo do edital vs baseline, e
inclusões/exclusões/não-conformidades de escopo por fornecedor (ótica
técnica). Recebe também a taxa de desconto e a moeda de referência
informadas pelo consultor.

Sua tarefa é tornar os preços COMPARÁVEIS entre si e contra o baseline,
isolando o que é "preço base equivalente" do que é "ajuste por escopo
diferente" — nunca misture os dois na mesma linha.

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois:

{
  "moeda_referencia": "<moeda usada na equalização — a informada pelo consultor>",
  "taxa_desconto_aplicada": <número, % informado pelo consultor>,
  "por_fornecedor": [
    {
      "fornecedor": "<nome>",
      "preco_base_equalizado": <número ou null — preço comparável, ANTES de on-tops>,
      "metodo_equalizacao": "<1-2 frases: como chegou nesse número, qual ramo do modelo de precificação usou>",
      "on_tops_escopo": [
        {"item": "<item do delta_escopo do edital>", "valor_estimado": <número ou null>, "direcao": "soma|subtrai", "origem": "edital_vs_baseline"}
      ],
      "on_tops_desvio": [
        {"item": "<inclusão/exclusão/não-conformidade desta proposta>", "valor_estimado": <número ou null>, "direcao": "soma|subtrai", "origem": "inclusao_escopo|exclusao_escopo|nao_conformidade_mandatoria"}
      ],
      "ajustes_condicoes": [
        {"tipo": "frete|impostos|prazo|moeda", "comentario": "<o que foi ajustado e por quê>", "valor_estimado": <número ou null>}
      ],
      "preco_total_equalizado": <número ou null — base + on-tops + ajustes>,
      "savings_vs_baseline": <número ou null — positivo = economia, negativo = aumento>,
      "savings_percentual": <número ou null>,
      "premissas": ["<premissa assumida para ESTE fornecedor>"],
      "faltantes": ["<dado que faltou para equalizar ESTE fornecedor>"]
    }
  ],
  "sintese_comparativa": "<parágrafo: como os fornecedores se posicionam em preço equalizado, sem recomendar qual escolher>",
  "premissas_gerais": ["<premissa que vale para a equalização como um todo>"],
  "faltantes_gerais": ["<limitação geral desta equalização>"]
}

Regras de ramificação por modelo de precificação (decida o método olhando
modelo_precificacao_ofertado de cada proposta, que pode diferir do detectado
na Etapa 1):
- hora-homem: equalize por taxa horária × volume de referência do baseline
  (se não houver volume de referência, registre em faltantes e equalize
  pela taxa unitária apenas, sinalizando a limitação).
- por_funcionario: equalize por custo/posto × headcount de referência do
  baseline; mesma ressalva se não houver headcount de referência.
- mensal_fixo: comparação direta, anualizando (mensal × 12) se necessário.
- variavel_por_consumo: precisa do volume de referência do baseline; sem
  ele, equalização fica marcada como aproximada e registrada em faltantes.
- tpq: equalize item a item pelos valores unitários informados.
- misto: trate cada componente do preço pelo método que lhe cabe, e explique
  em metodo_equalizacao como os componentes foram combinados.

Regras gerais:
- NUNCA misture on-top de escopo (origem: mudança edital vs baseline) com
  on-top de desvio (origem: diferença entre o que ESTA proposta oferece e o
  que as outras oferecem, ou não-conformidade mandatória). São rastreáveis
  separadamente mesmo que o efeito final no preço seja somado.
- Quando valor_estimado de um on-top não puder ser calculado com precisão,
  use null e explique a direção qualitativa (soma/subtrai) mesmo assim —
  não invente número preciso sem base.
- NÃO recomende qual fornecedor escolher — isso é Etapa 7. Aqui é só tornar
  os números comparáveis e mostrar o savings.
- Se uma proposta não tiver preco_total_proposto (da extração comercial),
  registre em faltantes que a equalização desse fornecedor ficou incompleta,
  mas ainda assim preencha o que for possível com os itens_precificados.
- LIMITE DE TAMANHO: on_tops_escopo, on_tops_desvio e ajustes_condicoes
  máximo 8 itens cada por fornecedor; premissas e faltantes (por fornecedor
  e gerais) máximo 5 itens cada.
  O JSON completo deve caber em 7000 tokens.
"""


# ---------------------------------------------------------------------------
# Montagem de contexto (lê do Estudo, não relê documentos brutos)
# ---------------------------------------------------------------------------

def _resumo_baseline_comercial_ctx(estudo) -> str:
    if not estudo.baseline:
        return "Baseline comercial: não disponível."
    com = estudo.baseline.get("comercial", {})
    return (
        f"Baseline comercial disponível.\n"
        f"Preço anual atual: {com.get('preco_anual_total')} "
        f"(base de anualização: {com.get('base_anualização', '—')})\n"
        f"Valores unitários de referência: "
        f"{json.dumps(com.get('valores_unitarios', []), ensure_ascii=False)}"
    )


def _resumo_delta_escopo_ctx(estudo) -> str:
    delta = (estudo.edital or {}).get("delta_escopo", {})
    if not delta.get("tem_baseline"):
        return "Delta de escopo (edital vs baseline): não disponível."
    linhas = ["DELTA DE ESCOPO (edital vs baseline) — fonte dos on-tops de escopo:"]
    for a in delta.get("adicionados", []):
        linhas.append(f"- ADICIONADO: {a.get('item','')} (impacto de custo: {a.get('impacto_custo','?')})")
    for r in delta.get("removidos", []):
        linhas.append(f"- REMOVIDO: {r.get('item','')} (impacto de custo: {r.get('impacto_custo','?')})")
    for m in delta.get("modificados", []):
        linhas.append(
            f"- MODIFICADO: {m.get('item','')} — {m.get('antes','?')} -> {m.get('depois','?')} "
            f"(impacto de custo: {m.get('impacto_custo','?')})"
        )
    return "\n".join(linhas)


def _resumo_propostas_tecnicas_ctx(estudo) -> str:
    propostas = estudo.propostas_tecnicas or []
    if not propostas:
        return "Propostas técnicas: nenhuma avaliação disponível."
    blocos = ["AVALIAÇÃO TÉCNICA POR FORNECEDOR — fonte dos on-tops de desvio:"]
    for p in propostas:
        linhas = [f"=== {p.get('fornecedor','?')} ==="]
        if p.get("nao_cumpre_mandatorio"):
            linhas.append(
                f"NÃO CUMPRE MANDATÓRIO: {', '.join(p.get('mandatorios_nao_cumpridos', []))}"
            )
        incl = p.get("inclusoes_escopo", [])
        if incl:
            linhas.append(f"Inclusões de escopo (só este fornecedor): {', '.join(incl)}")
        excl = p.get("exclusoes_escopo", [])
        if excl:
            linhas.append(f"Exclusões de escopo (este fornecedor deixa de fora): {', '.join(excl)}")
        blocos.append("\n".join(linhas))
    return "\n\n".join(blocos)


def _resumo_propostas_comerciais_ctx(estudo) -> str:
    propostas = estudo.propostas_comerciais or []
    if not propostas:
        return "Propostas comerciais: nenhuma extração disponível."
    blocos = ["DADOS COMERCIAIS POR FORNECEDOR:"]
    for p in propostas:
        linhas = [f"=== {p.get('fornecedor','?')} ==="]
        linhas.append(f"Modelo de precificação ofertado: {p.get('modelo_precificacao_ofertado','—')}")
        linhas.append(f"Moeda: {p.get('moeda','—')}")
        linhas.append(f"Preço total proposto: {p.get('preco_total_proposto')}")
        linhas.append(f"Base de anualização: {p.get('base_anualizacao','—')}")
        linhas.append(f"Impostos inclusos: {p.get('impostos_inclusos','—')} | Frete incluso: {p.get('frete_incluso','—')}")
        linhas.append(f"Condições de pagamento: {p.get('condicoes_pagamento','—')} | Reajuste: {p.get('reajuste','—')}")
        itens = p.get("itens_precificados", [])
        if itens:
            linhas.append(f"Itens precificados: {json.dumps(itens, ensure_ascii=False)}")
        blocos.append("\n".join(linhas))
    return "\n\n".join(blocos)


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
                "Estudo com muitos fornecedores/itens — verifique o volume de dados."
            )


# ---------------------------------------------------------------------------
# Checkpoint: taxa de desconto e moeda (via chatbox, bloqueia o fluxo)
# ---------------------------------------------------------------------------

def precisa_checkpoint_etapa6(estudo) -> bool:
    """True se taxa_desconto ou regra_moeda ainda não foram informadas."""
    return estudo.taxa_desconto is None or estudo.regra_moeda is None


def confirmar_taxa_e_moeda(estudo, taxa_desconto: float, regra_moeda: str) -> str:
    """
    Chamada quando o consultor informa taxa de desconto e moeda via chatbox.
    Grava no Estudo e registra a premissa.
    """
    estudo.taxa_desconto = taxa_desconto
    estudo.regra_moeda = regra_moeda
    estudo.add_premissa(
        f"Equalização comercial usou taxa de desconto de {taxa_desconto}% "
        f"e moeda de referência {regra_moeda}, informadas pelo consultor."
    )
    return f"✅ Taxa de desconto **{taxa_desconto}%** e moeda **{regra_moeda}** registradas."


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa6(estudo) -> dict:
    """
    Executa a Etapa 6 completa. NÃO chama a IA se o checkpoint de taxa de
    desconto/moeda ainda não foi respondido — quem chama esta função deve
    checar precisa_checkpoint_etapa6(estudo) antes.

    Retorna dict com:
        - tem_dados : bool
        - analise   : dict completo (JSON do Claude) ou None
        - resumo    : texto legível pra UI
    """
    if precisa_checkpoint_etapa6(estudo):
        msg = "Taxa de desconto e/ou moeda de referência ainda não informadas — Etapa 6 não pode rodar."
        return {"tem_dados": False, "analise": None, "resumo": f"⚠️ {msg}"}

    if not estudo.propostas_comerciais:
        msg = "Nenhuma proposta comercial extraída (Etapa 4B) — Etapa 6 não pôde rodar."
        estudo.add_faltante(msg)
        estudo.equalizacao_comercial = None
        return {"tem_dados": False, "analise": None, "resumo": f"⚠️ {msg}"}

    contexto = (
        f"Categoria: {estudo.categoria}\n"
        f"Modelo de precificação detectado (Etapa 1): {estudo.modelo_precificacao}\n"
        f"Micro-categoria: {estudo.micro_categoria or '—'}\n"
        f"Taxa de desconto informada pelo consultor: {estudo.taxa_desconto}%\n"
        f"Moeda de referência informada pelo consultor: {estudo.regra_moeda}\n\n"
        f"{_resumo_baseline_comercial_ctx(estudo)}\n\n"
        f"{_resumo_delta_escopo_ctx(estudo)}\n\n"
        f"{_resumo_propostas_tecnicas_ctx(estudo)}\n\n"
        f"{_resumo_propostas_comerciais_ctx(estudo)}"
    )

    with st.spinner("Etapa 6 — equalizando comercialmente as propostas..."):
        resposta_bruta = call_claude(
            messages=[{"role": "user", "content": contexto}],
            system=SYSTEM_EQUALIZACAO,
            max_tokens=MAX_TOKENS_ETAPA6,
        )

    try:
        analise = _parse_resposta(resposta_bruta)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Erro ao interpretar resposta da IA na Etapa 6: {e}\n\nResposta bruta:\n{resposta_bruta}")
        st.stop()

    estudo.equalizacao_comercial = analise

    for p in analise.get("premissas_gerais", []):
        estudo.add_premissa(p)
    for f in analise.get("faltantes_gerais", []):
        estudo.add_faltante(f)
    for forn in analise.get("por_fornecedor", []):
        nome = forn.get("fornecedor", "?")
        for p in forn.get("premissas", []):
            estudo.add_premissa(f"[{nome}] {p}")
        for f in forn.get("faltantes", []):
            estudo.add_faltante(f"[{nome}] {f}")

    estudo.etapa_atual = 6

    resumo = _montar_resumo(analise)
    return {"tem_dados": True, "analise": analise, "resumo": resumo}


def _montar_resumo(analise: dict) -> str:
    linhas = []

    linhas.append(
        f"**Equalização comercial** — moeda: {analise.get('moeda_referencia','—')} · "
        f"taxa de desconto aplicada: {analise.get('taxa_desconto_aplicada','—')}%"
    )

    sintese = analise.get("sintese_comparativa")
    if sintese:
        linhas.append(f"\n**Síntese comparativa:** {sintese}")

    for forn in analise.get("por_fornecedor", []):
        linhas.append(f"\n---\n### {forn.get('fornecedor','?')}")

        base = forn.get("preco_base_equalizado")
        total = forn.get("preco_total_equalizado")
        savings = forn.get("savings_vs_baseline")
        savings_pct = forn.get("savings_percentual")

        if base is not None:
            linhas.append(f"**Preço base equalizado:** {base:,.2f}")
        linhas.append(f"_Método: {forn.get('metodo_equalizacao','—')}_")

        on_tops_escopo = forn.get("on_tops_escopo", [])
        if on_tops_escopo:
            linhas.append("\n**On-tops de escopo (edital vs baseline):**")
            for o in on_tops_escopo:
                sinal = "+" if o.get("direcao") == "soma" else "−"
                valor = o.get("valor_estimado")
                valor_str = f"{sinal}{valor:,.2f}" if valor is not None else f"{sinal}(não estimado)"
                linhas.append(f"- {o.get('item','')}: {valor_str}")

        on_tops_desvio = forn.get("on_tops_desvio", [])
        if on_tops_desvio:
            linhas.append("\n**On-tops de desvio (inclusão/exclusão/não-conformidade):**")
            for o in on_tops_desvio:
                sinal = "+" if o.get("direcao") == "soma" else "−"
                valor = o.get("valor_estimado")
                valor_str = f"{sinal}{valor:,.2f}" if valor is not None else f"{sinal}(não estimado)"
                linhas.append(f"- [{o.get('origem','?')}] {o.get('item','')}: {valor_str}")

        ajustes = forn.get("ajustes_condicoes", [])
        if ajustes:
            linhas.append("\n**Ajustes de condições (frete/impostos/prazo/moeda):**")
            for a in ajustes:
                valor = a.get("valor_estimado")
                valor_str = f"{valor:,.2f}" if valor is not None else "(não estimado)"
                linhas.append(f"- [{a.get('tipo','?')}] {a.get('comentario','')}: {valor_str}")

        if total is not None:
            linhas.append(f"\n**Preço total equalizado:** {total:,.2f}")
        if savings is not None:
            sinal_s = "economia" if savings >= 0 else "aumento"
            pct_str = f" ({savings_pct:.1f}%)" if savings_pct is not None else ""
            linhas.append(f"**Savings vs baseline:** {sinal_s} de {abs(savings):,.2f}{pct_str}")

    faltantes = analise.get("faltantes_gerais", [])
    if faltantes:
        linhas.append("\n**Limitações desta equalização:**")
        for f in faltantes:
            linhas.append(f"- {f}")

    return "\n".join(linhas)
