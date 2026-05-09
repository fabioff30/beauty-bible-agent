"""
Beauty Advisor Agent - AI conversational agent for beauty recommendations
"""

import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class BeautyAdvisorAgent:
    """AI agent that provides personalized beauty advice and product recommendations"""

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
        self.model = os.getenv('AI_MODEL', 'openai/gpt-4o-mini')
        
        # Conversation context
        self.conversations = {}
        
        # System prompt for beauty advisor
        self.system_prompt = """Você é a Nina, uma consultora de beleza especializada da Beauty Bible.
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

Produtos disponíveis na linha Dani:
{dani_products}
"""

    def _get_system_prompt(self, skin_analysis: Optional[Dict] = None) -> str:
        """Build system prompt with context"""
        # Get product summary
        products = self.product_db._get_sample_products()
        product_summary = ""
        for p in products[:5]:
            product_summary += f"- {p['name']}: R${p['price']} - {p['description'][:80]}...\n"
        
        prompt = self.system_prompt.format(dani_products=product_summary.strip())
        
        if skin_analysis:
            prompt += f"""

DADOS DA ANÁLISE DE PELE DA CLIENTE:
- Tom de pele: {skin_analysis.get('skin_tone', 'N/D')}
- Tipo de pele: {skin_analysis.get('skin_type', 'N/D')}
- Subtom: {skin_analysis.get('undertone', 'N/D')}
- Concerns: {', '.join(skin_analysis.get('concerns', [])) or 'Nenhum identificado'}
- Confiança da análise: {skin_analysis.get('confidence', 'N/D')}

Use estes dados para personalizar suas recomendações."""
        
        prompt += f"""
Data atual: {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
        return prompt

    async def get_response(
        self,
        user_message: str,
        user_id: int,
        skin_analysis: Optional[Dict] = None
    ) -> str:
        """
        Generate AI response to user message
        
        Args:
            user_message: User's text message
            user_id: Telegram user ID
            skin_analysis: Previous skin analysis results
            
        Returns:
            AI response text
        """
        # Track conversation
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        
        self.conversations[user_id].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep only last 10 messages
        if len(self.conversations[user_id]) > 20:
            self.conversations[user_id] = self.conversations[user_id][-20:]
        
        # Build messages for API
        system_prompt = self._get_system_prompt(skin_analysis)
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add conversation history
        for msg in self.conversations[user_id][-10:]:
            messages.append({"role": msg['role'], "content": msg['content']})
        
        try:
            response = await self._call_ai_api(messages)
            
            # Store response
            self.conversations[user_id].append({
                'role': 'assistant',
                'content': response,
                'timestamp': datetime.now().isoformat()
            })
            
            return response
            
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return self._get_fallback_response(user_message, skin_analysis)

    async def _call_ai_api(self, messages: List[Dict]) -> str:
        """Call AI API for response"""
        
        if self.provider == 'openrouter':
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
                "HTTP-Referer": "https://beautybible.app",
                "X-Title": "Beauty Bible",
                "Content-Type": "application/json"
            }
        elif self.provider == 'openai':
            api_url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "Content-Type": "application/json"
            }
        elif self.provider == 'gemini':
            return await self._call_gemini(messages)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 800,
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content']

    async def _call_gemini(self, messages: List[Dict]) -> str:
        """Call Google Gemini API"""
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Convert messages to Gemini format
            prompt = ""
            for msg in messages:
                if msg['role'] == 'system':
                    prompt += f"INSTRUÇÕES: {msg['content']}\n\n"
                elif msg['role'] == 'user':
                    prompt += f"Usuária: {msg['content']}\n"
                elif msg['role'] == 'assistant':
                    prompt += f"Assistente: {msg['content']}\n"
            
            response = model.generate_content(prompt)
            return response.text
            
        except ImportError:
            raise Exception("Gemini SDK not installed")

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