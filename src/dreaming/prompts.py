"""
Sleep-time consolidation prompts.

Two tasks:
  1) extract_facts — pull durable, atomic facts from a chunk of conversation
  2) update_summary — produce/update a rolling summary covering the user's history

Both prompts FORCE JSON output for parseable downstream handling.
"""

FACT_KEYS_GUIDE = """
Chaves preferidas (use estas quando possível, mas pode criar outras):
- allergy.<substancia>          (ex: allergy.fragrance = "true")
- intolerance.<substancia>      (ex: intolerance.retinol = "moderada")
- budget                        (ex: "R$150-200/mês")
- preference.vegan              (true/false)
- preference.cruelty_free       (true/false)
- preference.fragrance_free     (true/false)
- preference.brand              (ex: "prefere marcas nacionais")
- lifestyle.sun_exposure        (alta/media/baixa)
- lifestyle.makeup_frequency    (diária/eventos/raramente)
- routine.morning_steps         (número ou lista)
- routine.night_steps           (número ou lista)
- goal                          (ex: "reduzir oleosidade da zona T")
- product_tried.<id>            (ex: product_tried.dani-radiance-serum = "loved")
- skin_change.<concern>         (ex: "piorou nos últimos meses")
- age_range                     (ex: "25-30")
- pregnancy_status              (relevante para contraindicações)
"""


EXTRACT_FACTS_SYSTEM = f"""Você é um extrator de memória para um agente de beleza chamado BB.
Sua função é ler mensagens recentes entre a cliente e a BB, e extrair APENAS fatos duráveis sobre a cliente — coisas que continuariam verdadeiras semanas/meses depois.

NÃO EXTRAIA:
- saudações, agradecimentos, small talk
- estados temporários ("hoje estou cansada")
- perguntas que a cliente fez
- opiniões da BB

EXTRAIA:
- alergias, intolerâncias, sensibilidades
- orçamento, preferências (vegano, sem fragrância, etc.)
- objetivos cosméticos persistentes
- produtos que a cliente diz já ter usado e o resultado
- contexto de vida relevante (idade, exposição solar, rotina, gravidez)

{FACT_KEYS_GUIDE}

REGRAS DE OUTPUT:
- Responda APENAS JSON válido, sem markdown nem explicação.
- Schema: {{"facts": [{{"key": "string", "value": "string", "confidence": 0.0-1.0}}]}}
- Se não houver nada novo para extrair, retorne {{"facts": []}}
- Confidence 0.9-1.0 quando a cliente afirmou explicitamente; 0.6-0.8 quando inferido.
- Valores curtos e canônicos. Sem PII (telefones, emails, CPF — já estão redigidos como [TEL], [EMAIL], [CPF]).
"""


SUMMARY_SYSTEM = """Você é um consolidador de memória para a BB, consultora de beleza.
Sua função é manter um RESUMO ROLANTE atualizado sobre a cliente, baseado no resumo anterior + novas mensagens.

O resumo precisa caber em ~400 palavras, em português brasileiro, escrito em terceira pessoa.
Foque em:
- perfil de pele e concerns confirmados
- preferências e restrições recorrentes
- jornada/objetivos atuais da cliente
- produtos discutidos e o desfecho (recomendado, comprado, gostou, rejeitou)
- tópicos abertos para retomar na próxima conversa

NÃO inclua:
- mensagens individuais literais
- saudações ou small talk
- conjecturas sem base

REGRAS DE OUTPUT:
- Responda APENAS JSON válido: {"summary": "texto do resumo aqui"}
- Sem markdown, sem explicação.
"""


def build_extract_user_prompt(messages: list[dict]) -> str:
    """Format the conversation chunk for the fact extractor."""
    lines = []
    for m in messages:
        role = 'Cliente' if m['role'] == 'user' else 'BB'
        lines.append(f"{role}: {m['content_redacted']}")
    return "Mensagens recentes:\n" + "\n".join(lines)


def build_summary_user_prompt(previous_summary: str | None, new_messages: list[dict]) -> str:
    parts = []
    if previous_summary:
        parts.append(f"RESUMO ANTERIOR:\n{previous_summary}\n")
    else:
        parts.append("RESUMO ANTERIOR: (nenhum — esta é a primeira consolidação)\n")
    parts.append("NOVAS MENSAGENS:")
    for m in new_messages:
        role = 'Cliente' if m['role'] == 'user' else 'BB'
        parts.append(f"{role}: {m['content_redacted']}")
    return "\n".join(parts)
