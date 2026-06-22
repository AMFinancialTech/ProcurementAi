"""
etapa1.py — Etapa 1: Entendimento e Classificação dos Documentos.

O que faz:
1. Lê todos os arquivos enviados pelo usuário.
2. Pede ao Claude pra:
   a) classificar cada arquivo (edital / baseline / proposta_combinada /
      proposta_tecnica / proposta_comercial / fornecedor / desconhecido);
   b) identificar o CLIENTE (empresa compradora) a partir do edital/baseline;
   c) agrupar as propostas em PROPONENTES — cada proponente é um fornecedor,
      e junta a técnica + a comercial dele (ou 1 combinada) sob um mesmo ID.
3. Detecta a categoria (Serviço / Material / Commodity) e o modelo de
   precificação.
4. Registra o que falta (sem edital, sem baseline, proponente sem comercial...)
   na Memória de Premissas do Estudo.
5. Devolve um resumo legível pro checkpoint de confirmação humana, já no formato
   Cenário Atual (As Is) + Proponente 1, 2, ... + nº de cenários de comparação.

O proponente é a chave que liga técnica↔comercial do MESMO fornecedor. É o que
impede a equalização (Etapa 6) de "dividir em 4" o que deveria ser 2 proponentes.
"""

import json
import re
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude
from leitura import read_file


# ---------------------------------------------------------------------------
# Prompt de classificação
# ---------------------------------------------------------------------------

SYSTEM_CLASSIFICACAO = """
Você é um especialista sênior em procurement e sourcing. Vai receber os
documentos de um processo de RFP/RFQ e precisa organizá-los para a análise.

TAREFA 1 — Classifique CADA documento em exatamente uma categoria:
- edital              → memorial descritivo, termos de referência, RFP, RFQ
                        (escopo técnico do cenário atual / As Is)
- baseline            → contrato atual, proposta anterior, tabela de preços
                        vigente, nota fiscal, planilha com preço atual
                        (escopo comercial do cenário atual / As Is)
- proposta_combinada  → proposta de UM fornecedor que mistura técnica e
                        comercial no mesmo arquivo
- proposta_tecnica    → só a parte técnica de uma proposta (metodologia,
                        equipe, prazo, conformidade) — sem preço
- proposta_comercial  → só preços de uma proposta (planilha de custos, TPQ)
- fornecedor          → apresentação institucional, portfólio, certidões,
                        habilitação (NÃO é proposta)
- desconhecido        → não se enquadra em nenhuma das anteriores

TAREFA 2 — Identifique o CLIENTE (a empresa COMPRADORA / contratante que conduz
o processo). Tire do edital ou do baseline. NÃO confunda com os fornecedores
proponentes. Se não der pra inferir com segurança, use null.

TAREFA 3 — Agrupe as propostas em PROPONENTES. Regras:
- Um proponente = um fornecedor concorrente.
- Junte a proposta_tecnica e a proposta_comercial do MESMO fornecedor sob o
  mesmo proponente (preenchendo os slots "tecnica" e "comercial").
- Uma proposta_combinada vira sozinha um proponente (preenche o slot
  "combinada"; deixa "tecnica" e "comercial" como null).
- Use o conteúdo (papel timbrado, razão social, nomes citados), não só o nome
  do arquivo, pra decidir de quem é cada documento.
- edital, baseline, fornecedor e desconhecido NÃO entram em proponentes.
- Se um fornecedor só mandou técnica (ou só comercial), tudo bem: crie o
  proponente com só o slot que existe; o outro fica null.
- Numere os IDs sequencialmente: "P1", "P2", "P3"...
- "fornecedor" do proponente é o nome canônico (use a forma mais completa e
  limpa que aparecer; o mesmo nome em técnica e comercial deve casar).

TAREFA 4 — Para o conjunto, informe:
- categoria: Serviço | Material | Commodity
- modelo_precificacao: hora-homem | por_funcionario | mensal_fixo |
  variavel_por_consumo | tpq | misto | desconhecido

LIMITES (respeite para o JSON não truncar):
- No máximo 15 documentos e no máximo 10 proponentes.
- Cada "resumo" com no máximo 1 frase curta.
- O JSON inteiro deve caber em 3500 tokens.

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois, no
formato:

{
  "cliente": "<empresa compradora ou null>",
  "documentos": [
    {
      "nome": "<nome do arquivo>",
      "tipo": "<categoria>",
      "fornecedor": "<nome do fornecedor se identificável, senão null>",
      "resumo": "<uma frase do que o documento contém>"
    }
  ],
  "proponentes": [
    {
      "id": "P1",
      "fornecedor": "<nome canônico do fornecedor>",
      "arquivos": {
        "tecnica": "<nome do arquivo ou null>",
        "comercial": "<nome do arquivo ou null>",
        "combinada": "<nome do arquivo ou null>"
      }
    }
  ],
  "categoria": "<Serviço | Material | Commodity>",
  "modelo_precificacao": "<valor>",
  "obs_precificacao": "<explicação breve do modelo detectado>"
}
"""


def _montar_mensagem(documentos_lidos: list[dict]) -> str:
    """Monta o texto que vai pro Claude com todos os documentos."""
    partes = []
    for doc in documentos_lidos:
        texto = doc["texto"][:MAX_CHARS_PER_DOC]
        partes.append(f"=== DOCUMENTO: {doc['nome']} ===\n{texto}")
    return "\n\n".join(partes)


def _extrair_json(resposta_bruta: str) -> dict:
    """
    Extrai o JSON da resposta do Claude, tolerante a:
    - ```json ... ``` em volta;
    - texto/preâmbulo antes do objeto;
    - truncamento (tenta fechar chaves/colchetes abertos antes de desistir).

    Mesmo padrão de fallback de truncamento usado nas demais etapas (seção 7B).
    """
    texto = resposta_bruta.strip()

    # Remove cercas de código
    if texto.startswith("```"):
        linhas = texto.split("\n")
        texto = "\n".join(linhas[1:])
        if texto.rstrip().endswith("```"):
            texto = texto.rstrip()[:-3]
        texto = texto.strip()

    # Tolera preâmbulo: começa no primeiro "{"
    inicio = texto.find("{")
    if inicio > 0:
        texto = texto[inicio:]

    # Tentativa direta
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback de truncamento: fecha colchetes/chaves abertos
    candidato = texto
    # corta lixo após o último } ou ] que pareça fechar
    abre_c = candidato.count("{")
    fecha_c = candidato.count("}")
    abre_l = candidato.count("[")
    fecha_l = candidato.count("]")
    # remove vírgula pendente no fim
    candidato = re.sub(r",\s*$", "", candidato.rstrip())
    candidato += "]" * max(0, abre_l - fecha_l)
    candidato += "}" * max(0, abre_c - fecha_c)
    return json.loads(candidato)


def _recalcular_faltantes(estudo) -> list[str]:
    """
    Recalcula a lista de faltantes a partir dos documentos e proponentes atuais.
    Atualiza a Memória de Premissas do Estudo sem duplicar entradas.
    """
    tipos_presentes = {d.get("tipo") for d in estudo.documentos}
    faltantes = []

    tem_edital = "edital" in tipos_presentes
    tem_baseline = "baseline" in tipos_presentes
    tem_proposta = bool(estudo.proponentes) or bool(
        tipos_presentes & {"proposta_combinada", "proposta_tecnica", "proposta_comercial"}
    )

    if not tem_edital:
        faltantes.append(
            "Edital / memorial descritivo não identificado — comparação técnica "
            "usará as propostas como referência."
        )
    if not tem_baseline:
        faltantes.append(
            "Baseline (cenário atual) não identificado — savings será relativo "
            "entre propostas, sem âncora de custo atual."
        )
    if not tem_proposta:
        faltantes.append("Nenhuma proposta identificada — verifique os arquivos enviados.")

    # Proponente incompleto: tem técnica mas falta comercial (ou vice-versa)
    for p in estudo.proponentes:
        arq = p.get("arquivos", {})
        tem_comb = bool(arq.get("combinada"))
        tem_tec = bool(arq.get("tecnica"))
        tem_com = bool(arq.get("comercial"))
        nome = p.get("fornecedor", p.get("id", "?"))
        if tem_comb:
            continue
        if tem_tec and not tem_com:
            faltantes.append(
                f"Proponente {nome}: só tem proposta técnica, sem comercial — "
                "a equalização (Etapa 6) ficará sem preço para este fornecedor."
            )
        elif tem_com and not tem_tec:
            faltantes.append(
                f"Proponente {nome}: só tem proposta comercial, sem técnica — "
                "a comparação técnica (Etapa 5) ficará sem aderência para este fornecedor."
            )

    # Sincroniza com a Memória de Premissas (sem duplicar)
    for msg in faltantes:
        if msg not in estudo.faltantes:
            estudo.add_faltante(msg)

    return faltantes


def _montar_checkpoint(estudo, obs_precificacao: str, faltantes: list[str],
                       titulo: str = "Classificação dos documentos") -> str:
    """
    Monta o texto do checkpoint no formato:
      Cliente · Cenário Atual (As Is) · Proponente 1, 2... · nº de cenários.
    Reutilizado pela rodada inicial e pelo loop de correção.
    """
    docs = estudo.documentos
    por_tipo = lambda t: [d for d in docs if d.get("tipo") == t]

    linhas = [f"**{titulo}**\n"]

    # --- Cliente ---
    cli = estudo.cliente or "_não identificado_"
    linhas.append(f"**Cliente apoiado:** {cli}")
    if not estudo.cliente:
        linhas.append("_Não consegui inferir o cliente. Me diga: 'o cliente é X'._")
    linhas.append("")

    # --- Cenário Atual (As Is) ---
    linhas.append("**Cenário Atual (As Is)**")
    editais = por_tipo("edital")
    baselines = por_tipo("baseline")
    if editais:
        for d in editais:
            linhas.append(f"- Edital (escopo técnico): **{d['nome']}**")
    else:
        linhas.append("- Edital (escopo técnico): _ausente_")
    if baselines:
        for d in baselines:
            linhas.append(f"- Baseline (escopo comercial): **{d['nome']}**")
    else:
        linhas.append("- Baseline (escopo comercial): _ausente_")
    linhas.append("")

    # --- Proponentes ---
    props = estudo.proponentes or []
    if props:
        for i, p in enumerate(props, start=1):
            arq = p.get("arquivos", {})
            nome_forn = p.get("fornecedor") or "_fornecedor não identificado_"
            linhas.append(f"**Proponente {i} — Fornecedor: {nome_forn}**")
            if arq.get("combinada"):
                linhas.append(f"- Proposta combinada (técnica + comercial): {arq['combinada']}")
            else:
                linhas.append(f"- Proposta técnica: {arq.get('tecnica') or '_ausente_'}")
                linhas.append(f"- Proposta comercial: {arq.get('comercial') or '_ausente_'}")
            linhas.append("")
    else:
        linhas.append("_Nenhum proponente identificado._\n")

    # --- Nº de cenários de comparação ---
    n_prop = len(props)
    n_cenarios = (1 if (editais or baselines) else 0) + n_prop
    base_txt = "As Is" if (editais or baselines) else "(sem As Is)"
    nomes_prop = " + ".join(f"P{i}" for i in range(1, n_prop + 1))
    detalhe = f"{base_txt}" + (f" + {nomes_prop}" if n_prop else "")
    linhas.append(f"**Cenários de comparação:** {n_cenarios}  ({detalhe})")
    linhas.append("")

    # --- Categoria / modelo ---
    linhas.append(f"**Categoria detectada:** {estudo.categoria}")
    linhas.append(f"**Modelo de precificação:** {estudo.modelo_precificacao}")
    if obs_precificacao:
        linhas.append(f"_{obs_precificacao}_")

    # --- Faltantes ---
    if faltantes:
        linhas.append("\n**⚠️ Pontos de atenção:**")
        for f in faltantes:
            linhas.append(f"- {f}")

    # --- Instrução de confirmação ---
    linhas.append(
        "\n---\n**Confere?** Corrija qualquer coisa aqui no chat, por exemplo:\n"
        "- _\"o cliente é Mosaic Fertilizantes\"_\n"
        "- _\"o arquivo X é baseline, não proposta\"_\n"
        "- _\"a técnica X e a comercial Y são do mesmo fornecedor\"_\n"
        "- _\"junta o proponente 2 com o 3\"_\n\n"
        "Quando estiver certo, diga **'confirmo'** pra travar a Etapa 1."
    )
    return "\n".join(linhas)


def _gravar_dados(estudo, dados: dict, documentos_lidos: list[dict] | None) -> None:
    """Grava cliente, documentos, proponentes, categoria e modelo no Estudo."""
    estudo.cliente = dados.get("cliente") or estudo.cliente
    estudo.documentos = dados.get("documentos", [])
    estudo.proponentes = dados.get("proponentes", [])
    estudo.categoria = dados.get("categoria") or estudo.categoria
    estudo.modelo_precificacao = dados.get("modelo_precificacao") or estudo.modelo_precificacao

    # Reanexa o texto lido em cada doc (as etapas seguintes precisam do texto)
    if documentos_lidos:
        for doc_classificado in estudo.documentos:
            nome = doc_classificado.get("nome")
            for doc_lido in documentos_lidos:
                if doc_lido["nome"] == nome:
                    doc_classificado["texto"] = doc_lido["texto"]
                    break


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa1(estudo, arquivos_enviados: list) -> dict:
    """
    Executa a Etapa 1 completa: classifica, identifica cliente, agrupa
    proponentes, detecta categoria/modelo e monta o checkpoint.
    """
    if not arquivos_enviados:
        st.error("Nenhum arquivo enviado. Suba pelo menos uma proposta para começar.")
        st.stop()

    # 1. Ler todos os arquivos
    documentos_lidos = []
    for arq in arquivos_enviados:
        texto = read_file(arq)
        documentos_lidos.append({"nome": arq.name, "texto": texto})

    # 2. Classificar via Claude
    mensagem_usuario = _montar_mensagem(documentos_lidos)
    with st.spinner("Etapa 1 — classificando documentos e agrupando proponentes..."):
        resposta_bruta = call_claude(
            messages=[{"role": "user", "content": mensagem_usuario}],
            system=SYSTEM_CLASSIFICACAO,
            max_tokens=4000,
        )

    # 3. Parsear (tolerante a preâmbulo e truncamento)
    try:
        dados = _extrair_json(resposta_bruta)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(
            f"Erro ao interpretar a resposta da IA na Etapa 1: {e}\n\n"
            f"Resposta bruta:\n{resposta_bruta}"
        )
        st.stop()

    # 4. Gravar no Estudo
    _gravar_dados(estudo, dados, documentos_lidos)

    # 5. Faltantes → Memória de Premissas
    faltantes = _recalcular_faltantes(estudo)

    # Premissa específica: variável por consumo sem baseline
    tem_baseline = any(d.get("tipo") == "baseline" for d in estudo.documentos)
    if estudo.modelo_precificacao == "variavel_por_consumo" and not tem_baseline:
        premissa = (
            "Modelo variável por consumo detectado sem baseline com volume de "
            "referência. A Etapa 6 assumirá um volume de referência — registrado como premissa."
        )
        if premissa not in estudo.premissas:
            estudo.add_premissa(premissa)

    # 6. Checkpoint
    resumo_checkpoint = _montar_checkpoint(
        estudo, dados.get("obs_precificacao", ""), faltantes
    )

    # 7. Controle de etapa (fica em 1 até confirmar)
    estudo.etapa_atual = 1

    return {
        "cliente": estudo.cliente,
        "documentos": estudo.documentos,
        "proponentes": estudo.proponentes,
        "categoria": estudo.categoria,
        "modelo_precificacao": estudo.modelo_precificacao,
        "obs_precificacao": dados.get("obs_precificacao", ""),
        "faltantes": faltantes,
        "resumo_checkpoint": resumo_checkpoint,
    }


def aplicar_correcao_etapa1(estudo, correcao: str) -> str:
    """
    Recebe uma correção em linguagem natural (reclassificar doc, reagrupar
    proponente, trocar cliente, renomear fornecedor) e atualiza o Estudo via
    Claude. Retorna o checkpoint atualizado.
    """
    estado_atual = json.dumps(
        {
            "cliente": estudo.cliente,
            "documentos": [
                {k: v for k, v in d.items() if k != "texto"}  # não manda o texto cru
                for d in estudo.documentos
            ],
            "proponentes": estudo.proponentes,
            "categoria": estudo.categoria,
            "modelo_precificacao": estudo.modelo_precificacao,
        },
        ensure_ascii=False,
        indent=2,
    )

    system = """
Você é um assistente de procurement. O usuário quer corrigir a organização dos
documentos de um processo de RFP/RFQ (classificação, cliente, ou agrupamento de
proponentes).

Receba o estado atual (JSON) e a instrução do usuário. Aplique a correção e
devolva o estado COMPLETO atualizado, no MESMO formato JSON.

Regras de agrupamento (mantenha-as):
- Um proponente = um fornecedor. Junte técnica + comercial do mesmo fornecedor
  sob o mesmo proponente (slots "tecnica"/"comercial"). Uma proposta_combinada
  ocupa o slot "combinada" sozinha.
- edital, baseline, fornecedor e desconhecido NÃO entram em proponentes.
- Renumere os IDs dos proponentes sequencialmente (P1, P2...) após a mudança.
- Mantenha "obs_precificacao" se já existir.

LIMITES: máximo 15 documentos, máximo 10 proponentes, JSON em até 3500 tokens.
Devolva SOMENTE o JSON, sem texto antes ou depois, com as chaves:
cliente, documentos, proponentes, categoria, modelo_precificacao, obs_precificacao.
"""
    mensagem = f"Estado atual:\n{estado_atual}\n\nInstrução de correção:\n{correcao}"

    with st.spinner("Aplicando correção..."):
        resposta = call_claude(
            messages=[{"role": "user", "content": mensagem}],
            system=system,
            max_tokens=4000,
        )

    try:
        dados = _extrair_json(resposta)
    except (json.JSONDecodeError, ValueError):
        return "Não consegui interpretar a correção. Tente de novo, com mais detalhe."

    # Aceita tanto o dict completo quanto uma lista de documentos solta
    if isinstance(dados, list):
        dados = {"documentos": dados}

    # Grava (sem documentos_lidos: reaproveita o texto já anexado)
    textos_antigos = {d.get("nome"): d.get("texto") for d in estudo.documentos}
    _gravar_dados(estudo, dados, documentos_lidos=None)
    # Reanexa textos preservados
    for d in estudo.documentos:
        if not d.get("texto") and d.get("nome") in textos_antigos:
            d["texto"] = textos_antigos[d["nome"]]

    faltantes = _recalcular_faltantes(estudo)
    return _montar_checkpoint(
        estudo, dados.get("obs_precificacao", ""), faltantes,
        titulo="Após a correção"
    )
