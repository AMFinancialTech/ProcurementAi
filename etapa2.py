"""
etapa2.py — Etapa 2: Análise do Cenário Atual (Baseline).

O que faz:
1. Verifica se há baseline no Estudo (classificado na Etapa 1).
   Se não houver, registra premissa e encerra com aviso — não trava o fluxo.
2. Identifica a micro-categoria (Limpeza, Segurança, MRO, EPI, etc.)
   e grava no Estudo — ela configura os fatores de TCO e should-cost.
3. Separa a ótica técnica da comercial dentro do baseline.
4. Comercial:
   a. Preço atual total anualizado (com assumption explicado).
      Se a anualização for impossível sem dado, pergunta ao usuário.
   b. Valores unitários + Pareto (item a item se der, senão agregado).
   c. Retrato do cenário (fornecedores, escopo, gasto anual, top itens).
   d. TCO rápido: checklist de fatores não considerados no preço, guiado
      pela micro-categoria.
   e. Should-cost de razoabilidade: não é bottom-up, é checagem do modelo
      de preço + drivers que mais pesam.
5. Os fatores de TCO/should-cost ficam gravados no Estudo para reuso na
   Etapa 6.
"""

import json
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_BASELINE = """
Você é um especialista sênior em procurement e análise de custos.
Vai receber o conteúdo de um ou mais documentos classificados como baseline
(contrato atual, proposta anterior, tabela de preços vigente, nota fiscal,
e-mail com preço atual, etc.) e informações de contexto (categoria e modelo
de precificação já identificados).

Sua tarefa é produzir uma análise estruturada do cenário atual. Responda
SOMENTE com um objeto JSON válido, sem texto antes ou depois, no formato:

{
  "micro_categoria": "<ex.: Limpeza Predial | Segurança Patrimonial | MRO | EPI | Frota Terceirizada | ...>",
  "tecnica": {
    "escopo_atual": "<descrição do que é fornecido hoje>",
    "fornecedores_atuais": ["<fornecedor 1>", "<fornecedor 2>"],
    "observacoes": "<qualquer detalhe técnico relevante do baseline>"
  },
  "comercial": {
    "preco_anual_total": <número em reais, ou null se impossível calcular>,
    "base_anualização": "<como chegou ao anual: vigência do contrato / datas de NF / assumption de 12 meses / etc.>",
    "precisa_confirmar_anualização": <true se for irregular/complexo e precisar perguntar ao usuário, senão false>,
    "sugestao_periodo": "<se precisa_confirmar_anualização=true: período que o Claude julga mais preciso>",
    "valores_unitarios": [
      {"item": "<descrição>", "valor": <número>, "unidade": "<unidade>", "share_percent": <0-100 ou null>}
    ],
    "pareto": "<narrativa: onde está o dinheiro — top itens/serviços que concentram o gasto>",
    "retrato": "<parágrafo: fornecedores, escopo fornecido, gasto anual na categoria, itens de maior valor>"
  },
  "tco": {
    "fatores_nao_considerados": [
      {"fator": "<ex.: turnover de mão de obra>", "relevancia": "alta|média|baixa", "comentario": "<por que importa>"}
    ],
    "ressalva_geral": "<texto curto resumindo o que o preço atual não captura>"
  },
  "should_cost": {
    "razoabilidade_modelo": "<o modelo de precificação faz sentido para esta categoria? por quê?>",
    "drivers_principais": [
      {"driver": "<ex.: custo de mão de obra>", "peso_estimado": "alto|médio|baixo", "comentario": "<detalhe>"}
    ],
    "sintese": "<checagem de razoabilidade: o preço está dentro do esperado para esta categoria/escopo?>"
  },
  "premissas_registradas": [
    "<premissa 1 que a análise assumiu>",
    "<premissa 2>..."
  ],
  "faltantes": [
    "<dado que faltou e impactou a análise>"
  ]
}

Regras:
- Seja preciso nos números quando o dado existir. Quando não existir, use null
  e explique em premissas_registradas.
- TCO: guie pelos fatores da micro-categoria (serviço → turnover, mobilização,
  overhead de gestão, passivos trabalhistas; material → frete, estoque,
  obsolescência, custo de qualidade/rejeição, custo financeiro do prazo).
- Should-cost: NÃO faça bottom-up. Avalie razoabilidade e identifique os
  drivers de custo que mais pesam — sem precisar de índices de mercado.
- Se a anualização for impossível (tabela de preços sem período, por exemplo),
  marque precisa_confirmar_anualização=true e sugira o período mais razoável.
"""


def _textos_baseline(estudo) -> str:
    """Extrai e concatena o texto dos documentos classificados como baseline."""
    partes = []
    for doc in estudo.documentos:
        if doc.get("tipo") == "baseline":
            texto = doc.get("texto", "")[:MAX_CHARS_PER_DOC]
            partes.append(f"=== BASELINE: {doc['nome']} ===\n{texto}")
    return "\n\n".join(partes)


def _parse_resposta(resposta_bruta: str) -> dict:
    texto = resposta_bruta.strip()
    if texto.startswith("```"):
        linhas = texto.split("\n")
        texto = "\n".join(linhas[1:-1]).strip()
    return json.loads(texto)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa2(estudo) -> dict:
    """
    Executa a Etapa 2 completa.

    Parâmetros
    ----------
    estudo : objeto Estudo (de estudo.py) — já populado pela Etapa 1.

    Retorna
    -------
    resultado : dict com as chaves:
        - analise          : dict completo da análise (JSON do Claude)
        - tem_baseline     : bool
        - precisa_confirmar_anualização : bool
        - resumo           : texto legível pra exibir na UI
    """

    # 1. Verificar se há baseline
    tipos = {d.get("tipo") for d in estudo.documentos}
    if "baseline" not in tipos:
        msg = (
            "Baseline não identificado — Etapa 2 pulada. "
            "Análise de savings será relativa entre propostas, sem âncora de custo atual."
        )
        estudo.add_faltante(msg)
        return {
            "tem_baseline": False,
            "analise": None,
            "precisa_confirmar_anualização": False,
            "resumo": f"⚠️ {msg}",
        }

    # 2. Montar mensagem pro Claude
    texto_baseline = _textos_baseline(estudo)
    contexto = (
        f"Categoria: {estudo.categoria}\n"
        f"Modelo de precificação: {estudo.modelo_precificacao}\n\n"
        f"{texto_baseline}"
    )

    # 3. Chamar Claude
    with st.spinner("Etapa 2 — analisando baseline..."):
        resposta_bruta = call_claude(
            messages=[{"role": "user", "content": contexto}],
            system=SYSTEM_BASELINE,
            max_tokens=4000,
        )

    # 4. Parsear
    try:
        analise = _parse_resposta(resposta_bruta)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Erro ao interpretar resposta da IA na Etapa 2: {e}\n\nResposta bruta:\n{resposta_bruta}")
        st.stop()

    # 5. Gravar no Estudo
    estudo.micro_categoria = analise.get("micro_categoria")
    estudo.baseline = analise

    # Premissas e faltantes → Memória de Premissas
    for p in analise.get("premissas_registradas", []):
        estudo.add_premissa(p)
    for f in analise.get("faltantes", []):
        estudo.add_faltante(f)

    # 6. Montar resumo legível
    resumo = _montar_resumo(analise)

    estudo.etapa_atual = 2

    return {
        "tem_baseline": True,
        "analise": analise,
        "precisa_confirmar_anualização": analise.get("comercial", {}).get("precisa_confirmar_anualização", False),
        "resumo": resumo,
    }


def _montar_resumo(analise: dict) -> str:
    """Monta o texto de exibição da Etapa 2."""
    linhas = []

    # Micro-categoria
    linhas.append(f"**Micro-categoria identificada:** {analise.get('micro_categoria', '—')}")

    # Técnica
    tec = analise.get("tecnica", {})
    linhas.append(f"\n**Escopo atual:** {tec.get('escopo_atual', '—')}")
    fornecedores = tec.get("fornecedores_atuais", [])
    if fornecedores:
        linhas.append(f"**Fornecedores atuais:** {', '.join(fornecedores)}")

    # Comercial
    com = analise.get("comercial", {})
    preco = com.get("preco_anual_total")
    if preco:
        linhas.append(f"\n**Gasto anual atual:** R$ {preco:,.2f}")
        linhas.append(f"_Base de anualização: {com.get('base_anualização', '—')}_")
    else:
        linhas.append("\n**Gasto anual atual:** não foi possível calcular com os dados disponíveis.")

    if com.get("precisa_confirmar_anualização"):
        linhas.append(
            f"\n⚠️ **Anualização requer confirmação.** "
            f"Sugestão do Claude: {com.get('sugestao_periodo', '—')}. "
            f"Você confirma esse período ou prefere outro?"
        )

    pareto = com.get("pareto")
    if pareto:
        linhas.append(f"\n**Onde está o dinheiro:** {pareto}")

    retrato = com.get("retrato")
    if retrato:
        linhas.append(f"\n**Retrato do cenário:** {retrato}")

    # TCO
    tco = analise.get("tco", {})
    fatores = tco.get("fatores_nao_considerados", [])
    if fatores:
        linhas.append("\n**Fatores de TCO não capturados no preço atual:**")
        for f in fatores:
            linhas.append(f"- [{f.get('relevancia','?').upper()}] {f.get('fator','')}: {f.get('comentario','')}")
    ressalva = tco.get("ressalva_geral")
    if ressalva:
        linhas.append(f"_{ressalva}_")

    # Should-cost
    sc = analise.get("should_cost", {})
    sintese = sc.get("sintese")
    if sintese:
        linhas.append(f"\n**Should-cost (razoabilidade):** {sintese}")

    # Premissas
    premissas = analise.get("premissas_registradas", [])
    if premissas:
        linhas.append("\n**Premissas assumidas nesta etapa:**")
        for p in premissas:
            linhas.append(f"- {p}")

    return "\n".join(linhas)


def confirmar_periodo_anualização(estudo, periodo_informado: str) -> str:
    """
    Chamada quando o usuário informa o período de anualização via chatbox.
    Atualiza o baseline com a premissa registrada e devolve confirmação.
    """
    if estudo.baseline and "comercial" in estudo.baseline:
        estudo.baseline["comercial"]["base_anualização"] = periodo_informado
        estudo.baseline["comercial"]["precisa_confirmar_anualização"] = False

    premissa = f"Período de anualização do baseline definido pelo consultor: {periodo_informado}."
    estudo.add_premissa(premissa)

    return f"✅ Período registrado: **{periodo_informado}**. Premissa adicionada à Memória de Premissas."
