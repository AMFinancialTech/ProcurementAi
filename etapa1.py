"""
etapa1.py — Etapa 1: Entendimento e Classificação dos Documentos.

O que faz:
1. Lê todos os arquivos enviados pelo usuário.
2. Pede ao Claude pra classificar cada um (edital / proposta_combinada /
   proposta_tecnica / proposta_comercial / baseline / fornecedor / desconhecido).
3. Detecta a categoria (Serviço / Material / Commodity) e o modelo de
   precificação (hora-homem / por_funcionario / mensal_fixo /
   variavel_por_consumo / tpq / misto / desconhecido).
4. Registra o que falta (sem edital, sem baseline, etc.) na Memória de
   Premissas do Estudo.
5. Devolve um resumo legível pro checkpoint de confirmação humana.

O app (app_v2.py) chama rodar_etapa1() e depois exibe o checkpoint pro
usuário confirmar ou corrigir antes de seguir.
"""

import json
import streamlit as st

from config import MAX_CHARS_PER_DOC
from ia import call_claude
from leitura import read_file


# ---------------------------------------------------------------------------
# Prompt de classificação
# ---------------------------------------------------------------------------

SYSTEM_CLASSIFICACAO = """
Você é um especialista em procurement e sourcing. Vai receber uma lista de
documentos de uma licitação ou processo de RFP/RFQ.

Para CADA documento, classifique-o em exatamente uma das categorias:
- edital              → memorial descritivo, termos de referência, RFP, RFQ
- baseline            → contrato atual, proposta anterior, tabela de preços
                        vigente, nota fiscal, e-mail com preço atual,
                        qualquer doc com evidência de escopo e preço atuais
- proposta_combinada  → proposta que mistura seção técnica e comercial num
                        único arquivo
- proposta_tecnica    → somente a parte técnica de uma proposta (metodologia,
                        equipe, prazo, conformidade)
- proposta_comercial  → somente preços, planilha de custos, TPQ
- fornecedor          → apresentação institucional, portfólio, certidões,
                        documentos de habilitação
- desconhecido        → não se enquadra em nenhuma das anteriores

Depois, para o conjunto inteiro, informe:
- categoria: Serviço | Material | Commodity
- modelo_precificacao: hora-homem | por_funcionario | mensal_fixo |
  variavel_por_consumo | tpq | misto | desconhecido

Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois,
no seguinte formato:

{
  "documentos": [
    {
      "nome": "<nome do arquivo>",
      "tipo": "<categoria>",
      "fornecedor": "<nome do fornecedor se identificável, senão null>",
      "resumo": "<uma frase do que o documento contém>"
    }
  ],
  "categoria": "<Serviço | Material | Commodity>",
  "modelo_precificacao": "<valor>",
  "obs_precificacao": "<explicação breve do modelo detectado>"
}
"""


def _montar_mensagem(documentos_lidos: list[dict]) -> str:
    """
    Monta o texto que vai pro Claude com todos os documentos.
    documentos_lidos: lista de {nome, texto}
    """
    partes = []
    for doc in documentos_lidos:
        texto = doc["texto"][:MAX_CHARS_PER_DOC]
        partes.append(f"=== DOCUMENTO: {doc['nome']} ===\n{texto}")
    return "\n\n".join(partes)


def _parse_resposta(resposta_bruta: str) -> dict:
    """
    Extrai o JSON da resposta do Claude.
    Trata o caso em que o modelo coloca ```json ... ``` em volta.
    """
    texto = resposta_bruta.strip()
    if texto.startswith("```"):
        linhas = texto.split("\n")
        # Remove primeira e última linha (as ```)
        texto = "\n".join(linhas[1:-1]).strip()
    return json.loads(texto)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def rodar_etapa1(estudo, arquivos_enviados: list) -> dict:
    """
    Executa a Etapa 1 completa.

    Parâmetros
    ----------
    estudo          : objeto Estudo (de estudo.py)
    arquivos_enviados : lista de file-objects do Streamlit (st.file_uploader)

    Retorna
    -------
    resultado : dict com as chaves:
        - documentos      : lista classificada (nome, tipo, fornecedor, resumo)
        - categoria       : Serviço | Material | Commodity
        - modelo_precificacao
        - obs_precificacao
        - faltantes       : lista de strings (o que não foi encontrado)
        - resumo_checkpoint : texto legível pra exibir no checkpoint
    """

    if not arquivos_enviados:
        st.error("Nenhum arquivo enviado. Suba pelo menos uma proposta para começar.")
        st.stop()

    # 1. Ler todos os arquivos
    documentos_lidos = []
    for arq in arquivos_enviados:
        texto = read_file(arq)
        documentos_lidos.append({"nome": arq.name, "texto": texto})

    # 2. Pedir classificação ao Claude
    mensagem_usuario = _montar_mensagem(documentos_lidos)

    with st.spinner("Etapa 1 — classificando documentos..."):
        resposta_bruta = call_claude(
            messages=[{"role": "user", "content": mensagem_usuario}],
            system=SYSTEM_CLASSIFICACAO,
            max_tokens=2000,
        )

    # 3. Parsear resposta
    try:
        dados = _parse_resposta(resposta_bruta)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Erro ao interpretar a resposta da IA na Etapa 1: {e}\n\nResposta bruta:\n{resposta_bruta}")
        st.stop()

    # 4. Gravar no objeto Estudo
    estudo.documentos = dados.get("documentos", [])
    estudo.categoria = dados.get("categoria")
    estudo.modelo_precificacao = dados.get("modelo_precificacao")

    # Guardar o texto lido de cada doc no Estudo (as etapas seguintes precisam)
    for doc_classificado in estudo.documentos:
        nome = doc_classificado["nome"]
        for doc_lido in documentos_lidos:
            if doc_lido["nome"] == nome:
                doc_classificado["texto"] = doc_lido["texto"]
                break

    # 5. Detectar o que falta → Memória de Premissas
    tipos_presentes = {d["tipo"] for d in estudo.documentos}
    faltantes = []

    tem_edital = "edital" in tipos_presentes
    tem_baseline = "baseline" in tipos_presentes
    tem_proposta = bool(
        tipos_presentes & {"proposta_combinada", "proposta_tecnica", "proposta_comercial"}
    )

    if not tem_edital:
        msg = "Edital / memorial descritivo não identificado — comparação técnica usará propostas como referência."
        faltantes.append(msg)
        estudo.add_faltante(msg)

    if not tem_baseline:
        msg = "Baseline (cenário atual) não identificado — análise de savings será relativa entre propostas, sem âncora de custo atual."
        faltantes.append(msg)
        estudo.add_faltante(msg)

    if not tem_proposta:
        msg = "Nenhuma proposta identificada — verifique os arquivos enviados."
        faltantes.append(msg)
        estudo.add_faltante(msg)

    # Modelo de precificação "variável por consumo" sem baseline → premissa
    if estudo.modelo_precificacao == "variavel_por_consumo" and not tem_baseline:
        premissa = (
            "Modelo de precificação variável por consumo detectado, mas não há baseline com volume "
            "de referência. A Etapa 6 assumirá um volume de referência — registrado como premissa."
        )
        estudo.add_premissa(premissa)

    # 6. Montar texto do checkpoint
    linhas = ["**Documentos identificados:**\n"]
    for doc in estudo.documentos:
        fornecedor = f" — {doc['fornecedor']}" if doc.get("fornecedor") else ""
        linhas.append(f"- **{doc['nome']}** → `{doc['tipo']}`{fornecedor}")
        linhas.append(f"  _{doc.get('resumo', '')}_")

    linhas.append(f"\n**Categoria detectada:** {estudo.categoria}")
    linhas.append(f"**Modelo de precificação:** {estudo.modelo_precificacao}")
    linhas.append(f"_{dados.get('obs_precificacao', '')}_")

    if faltantes:
        linhas.append("\n**⚠️ O que não foi encontrado:**")
        for f in faltantes:
            linhas.append(f"- {f}")

    linhas.append(
        "\n---\n**Confirma essa classificação?** "
        "Se alguma estiver errada, me diga aqui no chat (ex.: 'o arquivo X é baseline, não proposta')."
    )

    resumo_checkpoint = "\n".join(linhas)

    # 7. Avançar o controle de etapa
    estudo.etapa_atual = 1  # Fica em 1 até o usuário confirmar no checkpoint

    return {
        "documentos": estudo.documentos,
        "categoria": estudo.categoria,
        "modelo_precificacao": estudo.modelo_precificacao,
        "obs_precificacao": dados.get("obs_precificacao", ""),
        "faltantes": faltantes,
        "resumo_checkpoint": resumo_checkpoint,
    }


def aplicar_correcao_etapa1(estudo, correcao: str) -> str:
    """
    Recebe uma correção em linguagem natural do usuário (ex.: "o arquivo X
    é baseline, não proposta") e atualiza o Estudo via Claude.

    Retorna o novo resumo do checkpoint pra exibir na tela.
    """
    lista_atual = json.dumps(estudo.documentos, ensure_ascii=False, indent=2)

    system = """
Você é um assistente de procurement. O usuário quer corrigir a classificação
de documentos de um processo de RFP/RFQ.

Receba a lista atual de documentos (JSON) e a instrução de correção do usuário.
Aplique a correção e devolva a lista atualizada no mesmo formato JSON.
Devolva SOMENTE o JSON, sem texto antes ou depois.
"""
    mensagem = f"""
Lista atual:
{lista_atual}

Instrução de correção:
{correcao}
"""
    with st.spinner("Aplicando correção..."):
        resposta = call_claude(
            messages=[{"role": "user", "content": mensagem}],
            system=system,
            max_tokens=1500,
        )

    try:
        novos_docs = _parse_resposta(resposta)
        # Claude pode devolver lista direta ou dict com chave "documentos"
        if isinstance(novos_docs, list):
            estudo.documentos = novos_docs
        elif isinstance(novos_docs, dict) and "documentos" in novos_docs:
            estudo.documentos = novos_docs["documentos"]
    except (json.JSONDecodeError, ValueError):
        return "Não consegui interpretar a correção. Tente novamente com mais detalhes."

    # Rebuild resumo
    linhas = ["**Documentos (após correção):**\n"]
    for doc in estudo.documentos:
        fornecedor = f" — {doc['fornecedor']}" if doc.get("fornecedor") else ""
        linhas.append(f"- **{doc['nome']}** → `{doc['tipo']}`{fornecedor}")
        linhas.append(f"  _{doc.get('resumo', '')}_")

    linhas.append(f"\n**Categoria:** {estudo.categoria}")
    linhas.append(f"**Modelo de precificação:** {estudo.modelo_precificacao}")
    linhas.append("\n**Confirma agora?** Se sim, diga 'confirmo' ou 'ok' pra avançar.")

    return "\n".join(linhas)
