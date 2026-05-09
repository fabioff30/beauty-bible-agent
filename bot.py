"""
Beauty Bible Agent - Main Entry Point
Agente de IA para recomendação de produtos de beleza via Telegram
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.skin_analyzer import SkinAnalyzer
from src.product_db import ProductDatabase
from src.agent import BeautyAdvisorAgent

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')


class BeautyBibleBot:
    """Main bot class for Beauty Bible Telegram bot"""
    
    def __init__(self):
        self.skin_analyzer = SkinAnalyzer()
        self.product_db = ProductDatabase()
        self.agent = BeautyAdvisorAgent(
            product_db=self.product_db,
            skin_analyzer=self.skin_analyzer
        )
        self.user_sessions = {}  # Store user conversation state
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = """
✨ *Bem-vinda ao Beauty Bible!* ✨

Sou seu assistente pessoal de beleza. Posso ajudar você a:

🔍 *Analisar sua pele* - Envie uma foto do seu rosto e eu analiso seu tom e tipo de pele

💄 *Recomendar produtos* - Com base na sua análise, sugiro os melhores produtos para você

📦 *Comparar preços* - Verificar preços em diferentes lojas

🧴 *Montar sua rotina* - Criar uma rotina de cuidados personalizada

Como posso ajudar você hoje?
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📚 *Comandos disponíveis:*

/start - Iniciar conversa
/help - Ver esta ajuda
/analyze - Analisar minha pele (envie uma foto)
/routine - Ver minha rotina recomendada
/products - Ver produtos recomendados para meu tipo de pele

💡 *Dicas:*
- Para análise de pele, tire uma foto com boa iluminação
- Você pode perguntar sobre ingredientes específicos
- Posso comparar produtos de diferentes marcas
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages for skin analysis"""
        user = update.effective_user
        logger.info(f"Received photo from user {user.id}")
        
        # Send processing message
        processing_msg = await update.message.reply_text(
            "📸 Analisando sua pele... Por favor aguarde..."
        )
        
        try:
            # Get the photo
            photo = update.message.photo[-1]  # Get highest resolution
            
            # Download the photo
            photo_file = await context.bot.get_file(photo.file_id)
            photos_dir = Path(__file__).parent / 'data' / 'user_photos'
            photos_dir.mkdir(parents=True, exist_ok=True)
            
            photo_path = photos_dir / f"{user.id}_{photo.file_id}.jpg"
            await photo_file.download_to_drive(photo_path)
            
            # Analyze the skin
            analysis_result = await self.skin_analyzer.analyze(photo_path)
            
            # Store analysis in user session
            self.user_sessions[user.id] = {
                'skin_analysis': analysis_result,
                'last_update': datetime.now()
            }
            
            # Generate recommendations
            recommendations = self.product_db.get_recommendations(
                skin_tone=analysis_result.get('skin_tone'),
                skin_type=analysis_result.get('skin_type'),
                concerns=analysis_result.get('concerns', [])
            )
            
            # Send results
            result_text = self._format_analysis_result(analysis_result, recommendations)
            await processing_msg.edit_text(result_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error analyzing photo: {e}")
            await processing_msg.edit_text(
                "❌ Desculpe, ocorreu um erro ao analisar sua foto. "
                "Tente novamente com uma foto com melhor iluminação."
            )
            
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        user = update.effective_user
        message_text = update.message.text
        
        logger.info(f"Message from user {user.id}: {message_text}")
        
        # Check if user has previous analysis
        user_session = self.user_sessions.get(user.id, {})
        
        # Get agent response
        response = await self.agent.get_response(
            user_message=message_text,
            user_id=user.id,
            skin_analysis=user_session.get('skin_analysis')
        )
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    def _format_analysis_result(self, analysis: dict, recommendations: list) -> str:
        """Format analysis result and recommendations for display"""
        text = "✨ *Análise da Sua Pele* ✨\n\n"
        
        # Skin analysis
        text += f"🎨 *Tom de Pele:* {analysis.get('skin_tone', 'Não identificado')}\n"
        text += f"💧 *Tipo de Pele:* {analysis.get('skin_type', 'Não identificado')}\n"
        
        if analysis.get('undertone'):
            text += f"🔸 *Subtom:* {analysis.get('undertone')}\n"
            
        if analysis.get('concerns'):
            text += "\n*Concerns identificados:*\n"
            for concern in analysis.get('concerns', []):
                text += f"  • {concern}\n"
                
        # Recommendations
        text += "\n" + "="*30 + "\n"
        text += "💡 *Produtos Recomendados:*\n\n"
        
        for i, rec in enumerate(recommendations[:5], 1):
            text += f"{i}. *{rec['name']}*\n"
            text += f"   💰 R$ {rec['price']}\n"
            text += f"   📝 {rec['description'][:80]}...\n\n"
            
        text += "\n💬 Quer mais detalhes sobre algum produto?"
        
        return text


async def main():
    """Main function to run the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables")
        print("❌ Erro: TELEGRAM_BOT_TOKEN não configurado!")
        print("   Configure no arquivo .env ou variável de ambiente")
        return
        
    bot = BeautyBibleBot()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("analyze", bot.start_command))
    application.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    logger.info("🤖 Beauty Bible Bot starting...")
    print("🤖 Beauty Bible Bot iniciado!")
    print("   Pressione Ctrl+C para parar")
    
    # Start polling
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())