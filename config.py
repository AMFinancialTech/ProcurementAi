"""
config.py — Configuração central do Analisador.

Junta num lugar só os valores que várias partes do app usam, pra você
mudar uma vez e valer em tudo. Não tem lógica aqui, só constantes.
"""

# Modelo do Claude usado em todas as chamadas de IA.
MODEL = "claude-sonnet-4-5-20250929"

# Limite de caracteres por documento enviado à IA.
# Controla o custo e garante que o texto cabe no contexto do modelo.
MAX_CHARS_PER_DOC = 30000
