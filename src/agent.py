"""
Beauty Advisor Agent (BB) - AI conversational agent for beauty recommendations.

User-facing persona: BB.
Internal codename: beauty_bible.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from src.db import storage
from src.llm import chat_completion, Sources

logger = logging.getLogger(__name__)


class BeautyAdvisorAgent:
    """BB — AI agent that provides personalized beauty advice and product recommendations."""

    def __init__(self, product_db, skin_analyzer):
        """
        Initialize the beauty advisor

        Args:
            product_db: ProductDatabase instance
            skin_analyzer: SkinAnalyzer instance
        """
        self.product_db = product_db
        self.skin_analyzer = skin_analyzer

        # AI model — Gemini SDK takes the model id without provider prefix.
        # _normalize_model() in llm.py also strips 'google/' if env still has it.
        self.model = os.getenv('AI_MODEL', 'gemini-2.5-flash')

        # System prompt for BB. Updated to enforce:
        # (a) short, chunked replies separated by <split>
        # (b) hard anti-hallucination guardrails (no fabricating links/prices/stock)
        # (c) one-shot examples of the desired cadence
        self.system_prompt = """Você é a BB, consultora pessoal de beleza da Beauty Bible.

PERSONA
- Amigável, acolhedora, entusiasmada. Conhecimento técnico mas acessível.
- Fala como amiga no WhatsApp, não como assistente formal.
- Linguagem feminina e empoderadora. Sempre em português brasileiro.

FORMATO DAS MENSAGENS (REGRA DURA)
- Responda em 1 a 4 mensagens curtas (1-2 frases cada). Nunca mande um bloco gigante.
- Separe cada mensagem com a tag literal <split> em uma linha sozinha.
- Faça UMA pergunta de cada vez. Espere a resposta antes de avançar.
- Sem markdown, sem asteriscos, sem listas com hífen ou bullet. Texto corrido.
- Emojis com moderação: no máximo 1 por mensagem, e nem sempre.

CONHECIMENTOS QUE VOCÊ TEM
- Skincare (ingredientes, rotinas, tipos de pele)
- Maquiagem (técnicas, produtos, tendências)
- Cabelo (tipos, tratamentos, finalizadores)
- Perfumaria (famílias olfativas, ocasiões)
- Nails (cuidados, tendências)

ANTI-ALUCINAÇÃO (CRÍTICO)
Você só pode afirmar como fato:
1. O que está no perfil da cliente (análise de pele, fatos persistentes, resumo).
2. O nome e a descrição dos produtos na lista de PRODUTOS DISPONÍVEIS abaixo.
3. Conhecimento estável de cosmetologia (como ingredientes funcionam, indicações de uso).

Você NÃO PODE inventar:
- Links de compra (NENHUM produto tem link confirmado ainda no sistema)
- Preços diferentes dos listados
- Estoque, disponibilidade, promoções, descontos
- Avaliações, rating, número de vendas
- Produtos de marcas concorrentes
- Notícias ou tendências do mercado em datas específicas

Quando perguntarem sobre algo que você não tem confirmado, recuse assim:
"Não tenho essa informação confirmada agora. Quer que eu pergunte pra equipe e te aviso?"

Se a cliente pedir pra apagar os dados, oriente-a a usar o comando /apagar_meus_dados.

EXEMPLOS DE RITMO (siga este tom e formato)

Exemplo 1 — recusa elegante de info que você não tem:
Cliente: BB, onde posso comprar o Dani Radiance Serum?
BB: Boa pergunta! 💛<split>Não tenho o link de compra confirmado por aqui ainda.<split>Quer que eu pergunte pra equipe e te aviso assim que tiver?

Exemplo 2 — conversa fluida, uma pergunta por vez:
Cliente: minha pele tá oleosa, o que faço?
BB: Entendi, isso incomoda mesmo.<split>Você usa hidratante hoje em dia?<split>E que tipo de limpeza tá fazendo de manhã?

Exemplo 3 — recomendação a partir do catálogo (use só o que está na lista):
Cliente: o que você sugere pra acne?
BB: A linha Dani tem opções legais pra isso. ✨<split>Pra começar, o Pure Cleansing Gel ajuda a controlar a oleosidade sem ressecar.<split>Quer que eu monte uma rotina simples pra você?

PRODUTOS DISPONÍVEIS
{dani_products}
"""

    def _get_system_prompt(
        self,
        skin_analysis: Optional[Dict] = None,
        rolling_summary: Optional[str] = None,
        facts: Optional[List[Dict]] = None,
    ) -> str:
        """Build system prompt with persisted user context."""
        # Full catalog (small enough to fit). Reminder appended so the LLM
        # knows that purchase_url is not yet available — must refuse instead.
        products = self.product_db._get_sample_products()
        product_lines = []
        for p in products:
            product_lines.append(
                f"- {p['name']} | categoria: {p.get('subcategory', '?')} "
                f"| R$ {p['price']} | {p['description'][:100]}"
            )
        product_lines.append("")
        product_lines.append(
            "(Lembrete: NENHUM destes produtos tem link de compra confirmado "
            "no sistema. Recuse educadamente quando perguntarem onde comprar.)"
        )
        product_summary = "\n".join(product_lines)

        prompt = self.system_prompt.format(dani_products=product_summary)

        if skin_analysis:
            prompt += f"""

DADOS DA ANÁLISE DE PELE DA CLIENTE:
- Tom de pele: {skin_analysis.get('skin_tone') or skin_analysis.get('skin_tone_name', 'N/D')}
- Tipo de pele: {skin_analysis.get('skin_type', 'N/D')}
- Subtom: {skin_analysis.get('undertone', 'N/D')}
- Concerns: {', '.join(skin_analysis.get('concerns', [])) or 'Nenhum identificado'}
- Confiança da análise: {skin_analysis.get('confidence', 'N/D')}

Use estes dados para personalizar suas recomendações."""

        if facts:
            prompt += "\n\nFATOS PERSISTENTES SOBRE A CLIENTE (use, mas não recite literalmente):\n"
            for f in facts[:15]:
                prompt += f"- {f['key']}: {f['value']}\n"

        if rolling_summary:
            prompt += f"\n\nRESUMO DAS CONVERSAS ANTERIORES:\n{rolling_summary}\n"

        prompt += f"\nData atual: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        return prompt

    async def present_analysis(self, user_id: int) -> Tuple[str, Sources]:
        """
        Read the just-persisted skin profile and produce a warm presentation
        of the analysis, ending with an open question about what the user
        wants to focus on. Uses the same persona/chunking rules as get_response.
        Returns (text, sources).
        """
        profile = await storage.get_profile(user_id)
        facts = await storage.list_facts(user_id)
        summary_row = await storage.get_summary(user_id, scope='rolling')

        system_prompt = self._get_system_prompt(
            skin_analysis=profile,
            rolling_summary=summary_row['summary'] if summary_row else None,
            facts=facts,
        )

        directive = (
            "A cliente acabou de me mandar uma foto e a análise dela está nos "
            "DADOS DA ANÁLISE DE PELE acima.\n\n"
            "Sua tarefa AGORA, nesta mensagem:\n"
            "1) Comente a análise dela de forma calorosa e acolhedora, em 2 ou 3 "
            "bolhas curtas. Destaque tom, tipo e 1-2 concerns principais sem "
            "soar relatório técnico. Use a primeira pessoa ('vi que', 'percebi').\n"
            "2) NÃO recomende produto específico ainda.\n"
            "3) Termine com UMA pergunta aberta convidando ela a escolher o caminho: "
            "exemplos — recomendação de produtos da nossa linha, montar uma rotina "
            "de skincare, tirar dúvida de algum cuidado, ou conversar sobre algo "
            "específico que ela queira melhorar.\n\n"
            "Lembre: 1-4 bolhas, separadas por <split>, sem markdown, no máximo "
            "1 emoji por bolha. Você é parceira da rotina dela, não vitrine."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": directive},
        ]
        # Grounding ON: analysis comments may reference real cosmetology context.
        return await chat_completion(messages, model=self.model, with_search=True)

    async def get_response(self, user_message: str, user_id: int) -> Tuple[str, Sources]:
        """
        Generate AI response, reading context from the persistent store.

        Args:
            user_message: User's text message (already PII-redacted upstream)
            user_id: Telegram user ID

        Returns:
            AI response text
        """
        # Load persisted context
        profile = await storage.get_profile(user_id)
        facts = await storage.list_facts(user_id)
        summary_row = await storage.get_summary(user_id, scope='rolling')
        history = await storage.recent_messages(user_id, limit=10)

        system_prompt = self._get_system_prompt(
            skin_analysis=profile,
            rolling_summary=summary_row['summary'] if summary_row else None,
            facts=facts,
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg['role'], "content": msg['content_redacted']})
        messages.append({"role": "user", "content": user_message})

        try:
            # Grounding ON: BB can cite real sources for "onde comprar", etc.
            return await chat_completion(messages, model=self.model, with_search=True)
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return self._get_fallback_response(user_message, profile), []

    def _get_fallback_response(self, user_message: str, skin_analysis: Optional[Dict]) -> str:
        """Generate fallback response when AI API is unavailable"""
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ['rotina', 'routine']):
            if skin_analysis:
                return self._generate_routine_response(skin_analysis)
            return "📸 Para criar uma rotina personalizada, primeiro preciso analisar sua pele. Envie uma foto do seu rosto com boa iluminação!"
        
        if any(word in message_lower for word in ['pele', 'tipo', 'tom']):
            if skin_analysis:
                return f"""✨ Sua análise atual mostra:
• Tom: {skin_analysis.get('skin_tone')}
• Tipo: {skin_analysis.get('skin_type')}
• Subtom: {skin_analysis.get('undertone', 'Não analisado')}

Posso recomendar produtos específicos para você!"""
            return "Ainda não tenho sua análise de pele. Me envie uma foto bem iluminada do seu rosto 📸"
        
        if any(word in message_lower for word in ['produto', 'recomenda', 'indicar']):
            if skin_analysis:
                return self._generate_recommendation_response(skin_analysis)
            return "Para recomendar produtos, preciso primeiro analisar sua pele. Envie uma foto! 🎯"
        
        return "💬 Olá! Posso analisar sua pele e recomendar produtos. Envie uma foto ou me diga o que procura!"

    def _generate_routine_response(self, skin_analysis: Dict) -> str:
        """Generate a skincare routine response"""
        routine = self.product_db.get_routine(
            skin_type=skin_analysis.get('skin_type'),
            skin_tone=skin_analysis.get('skin_tone')
        )
        
        response = "✨ *Sua Rotina Personalizada* ✨\n\n"
        
        response += "☀️ *MANHÃ:*\n"
        for product in routine.get('morning', []):
            response += f"   {product['name']} - R${product['price']}\n"
        response += "\n"
        
        response += "🌙 *NOITE:*\n"
        for product in routine.get('night', []):
            response += f"   {product['name']} - R${product['price']}\n"
        response += "\n"
        
        response += "📅 *SEMANAL:*\n"
        for product in routine.get('weekly', []):
            response += f"   {product['name']} - R${product['price']}\n"
        response += "\n"
        
        response += f"💰 *Total estimado:* R${routine.get('total_price', 0):.2f}\n"
        
        return response

    def _generate_recommendation_response(self, skin_analysis: Dict) -> str:
        """Generate product recommendation response"""
        recs = self.product_db.get_recommendations(
            skin_type=skin_analysis.get('skin_type'),
            skin_tone=skin_analysis.get('skin_tone'),
            concerns=skin_analysis.get('concerns', []),
            limit=5
        )
        
        response = "💄 *Top Produtos para Você* 💄\n\n"
        for i, rec in enumerate(recs, 1):
            response += f"{i}. *{rec['name']}*\n"
            response += f"   💰 R${rec['price']:.2f}\n"
            response += f"   📝 {rec['description'][:100]}...\n"
            if rec.get('match_reasons'):
                response += f"   ✅ {rec['match_reasons'][0]}\n"
            response += "\n"
        
        return response