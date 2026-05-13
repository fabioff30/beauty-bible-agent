"""
Beauty Advisor Agent (BB) - AI conversational agent for beauty recommendations.

User-facing persona: BB.
Internal codename: beauty_bible.
"""

import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

from src.db import storage
from src.llm import chat_completion

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

        # AI model configuration
        self.provider = os.getenv('AI_PROVIDER', 'openrouter')  # openrouter, openai, gemini
        self.model = os.getenv('AI_MODEL', 'google/gemini-2.5-flash')

        # System prompt for BB
        self.system_prompt = """Você é a BB, consultora de beleza pessoal da Beauty Bible.
Sua especialidade é recomendar produtos de beleza baseados na análise de pele da cliente.

Tons de voz:
- Amigável, acolhedora e entusiasmada
- Use emojis moderadamente para criar conexão
- Conhecimento técnico mas acessível
- Linguagem feminina e empoderadora
- Sempre em português brasileiro

Conhecimentos:
- Skincare (ingredientes, rotinas, tipos de pele)
- Maquiagem (técnicas, produtos, tendências)
- Cabelo (tipos, tratamentos, finalizadores)
- Perfumaria (famílias olfativas, ocasiões)
- Nails (tendências, cuidados)

IMPORTANTE:
- Se a usuária ainda não enviou foto, incentive-a a enviar para análise personalizada
- Baseie suas recomendações nos dados de análise de pele quando disponíveis
- Seja honesta sobre limitações dos produtos
- Pergunte sobre orçamento e preferências antes de recomendar
- Se a cliente pedir para esquecer/apagar seus dados, oriente-a a usar o comando /apagar_meus_dados

Produtos disponíveis na linha Dani:
{dani_products}
"""

    def _get_system_prompt(
        self,
        skin_analysis: Optional[Dict] = None,
        rolling_summary: Optional[str] = None,
        facts: Optional[List[Dict]] = None,
    ) -> str:
        """Build system prompt with persisted user context."""
        # Get product summary
        products = self.product_db._get_sample_products()
        product_summary = ""
        for p in products[:5]:
            product_summary += f"- {p['name']}: R${p['price']} - {p['description'][:80]}...\n"

        prompt = self.system_prompt.format(dani_products=product_summary.strip())

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

    async def get_response(self, user_message: str, user_id: int) -> str:
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
            return await chat_completion(messages, model=self.model)
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return self._get_fallback_response(user_message, profile)

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