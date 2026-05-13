"""
Beauty Bible Agent - Main Entry Point
Bot Telegram da BB (consultora pessoal de beleza) com memória persistente em SQLCipher.
"""

import os
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.skin_analyzer import SkinAnalyzer
from src.product_db import ProductDatabase
from src.agent import BeautyAdvisorAgent
from src.db import storage
from src.db.connection import init_db
from src.dreaming.scheduler import start_scheduler, stop_scheduler
from src.redact import redact_pii, hash_photo

# Load env: .env.local overrides .env
from dotenv import load_dotenv
load_dotenv()
load_dotenv('.env.local', override=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')


class BeautyBibleBot:
    """BB — Telegram bot front for the Beauty Bible agent."""

    def __init__(self):
        self.skin_analyzer = SkinAnalyzer()
        self.product_db = ProductDatabase()
        self.agent = BeautyAdvisorAgent(
            product_db=self.product_db,
            skin_analyzer=self.skin_analyzer,
        )

    # -----------------------------------------------------------
    # Commands
    # -----------------------------------------------------------
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await storage.ensure_user(user.id, user.username, user.first_name)
        await storage.record_consent(user.id)

        welcome_message = """
✨ *Oi, eu sou a BB!* ✨

Sua consultora pessoal de beleza. Posso te ajudar a:

🔍 *Analisar sua pele* — Envie uma foto do seu rosto e eu identifico seu tom, tipo e necessidades

💄 *Recomendar produtos* — Com base na análise, sugiro o que combina com você

🧴 *Montar sua rotina* — Cuidado personalizado, manhã e noite

📦 *Tirar dúvidas* — Sobre ingredientes, marcas, técnicas

Como posso te ajudar hoje?

_Seus dados são protegidos. Use /apagar\\_meus\\_dados a qualquer momento._
"""
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📚 *Comandos disponíveis:*

/start — Iniciar conversa
/help — Ver esta ajuda
/perfil — Ver minha análise de pele atual
/apagar\\_meus\\_dados — Apagar tudo o que a BB sabe sobre você

💡 *Dicas:*
- Para análise de pele, mande uma foto com boa luz
- Pode perguntar sobre ingredientes específicos
- A BB lembra das nossas conversas anteriores
"""
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        profile = await storage.get_profile(user.id)
        if not profile:
            await update.message.reply_text(
                "Ainda não temos sua análise! Me envie uma foto pra começarmos 📸"
            )
            return
        text = "✨ *Seu Perfil Atual* ✨\n\n"
        text += f"🎨 *Tom:* {profile.get('skin_tone_name') or 'N/D'}\n"
        text += f"💧 *Tipo:* {profile.get('skin_type') or 'N/D'}\n"
        text += f"🔸 *Subtom:* {profile.get('undertone') or 'N/D'}\n"
        concerns = profile.get('concerns', [])
        if concerns:
            text += "\n*Concerns:*\n" + "\n".join(f"  • {c}" for c in concerns)
        text += f"\n\n_Atualizado em {profile.get('updated_at')}_"
        await update.message.reply_text(text, parse_mode='Markdown')

    async def delete_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """LGPD Art. 18 — right to be forgotten."""
        user = update.effective_user
        counts = await storage.delete_user_data(user.id)
        total = sum(counts.values())
        await update.message.reply_text(
            f"🗑️ *Pronto.* Apaguei tudo o que tínhamos sobre você ({total} registros).\n\n"
            f"Se quiser voltar, é só me mandar um /start. 💛",
            parse_mode='Markdown',
        )
        logger.info(f"LGPD delete executed for user {user.id}: {counts}")

    # -----------------------------------------------------------
    # Photo handler
    # -----------------------------------------------------------
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await storage.ensure_user(user.id, user.username, user.first_name)
        logger.info(f"Received photo from user {user.id}")

        processing_msg = await update.message.reply_text(
            "📸 Analisando sua pele... só um instante..."
        )

        photo_path: Path | None = None
        try:
            photo = update.message.photo[-1]  # highest res
            photo_file = await context.bot.get_file(photo.file_id)
            photos_dir = Path(__file__).parent / 'data' / 'user_photos'
            photos_dir.mkdir(parents=True, exist_ok=True)

            photo_path = photos_dir / f"{user.id}_{photo.file_id}.jpg"
            await photo_file.download_to_drive(photo_path)

            # Hash before analysis (stable even after deletion)
            photo_bytes = photo_path.read_bytes()
            phash = hash_photo(photo_bytes)

            analysis = await self.skin_analyzer.analyze(photo_path)

            # Persist: profile snapshot + episodic event
            await storage.upsert_profile(user.id, analysis, photo_hash=phash)
            await storage.append_episode(
                user_id=user.id,
                kind='skin_analysis',
                summary=(
                    f"Análise de pele: tom {analysis.get('skin_tone', 'N/D')}, "
                    f"tipo {analysis.get('skin_type', 'N/D')}, "
                    f"subtom {analysis.get('undertone', 'N/D')}."
                ),
                payload={**analysis, 'photo_hash': phash},
                importance=0.9,
            )

            recommendations = self.product_db.get_recommendations(
                skin_tone=analysis.get('skin_tone'),
                skin_type=analysis.get('skin_type'),
                concerns=analysis.get('concerns', []),
            )

            result_text = self._format_analysis_result(analysis, recommendations)
            await processing_msg.edit_text(result_text, parse_mode='Markdown')

        except Exception as e:
            logger.exception(f"Error analyzing photo: {e}")
            await processing_msg.edit_text(
                "❌ Desculpe, deu erro ao analisar sua foto. "
                "Tenta de novo com mais luz?"
            )
        finally:
            # Always delete the raw photo — we only retain the structured analysis + hash
            if photo_path and photo_path.exists():
                try:
                    photo_path.unlink()
                except OSError as e:
                    logger.warning(f"Could not delete {photo_path}: {e}")

    # -----------------------------------------------------------
    # Text handler
    # -----------------------------------------------------------
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await storage.ensure_user(user.id, user.username, user.first_name)

        raw = update.message.text
        redacted = redact_pii(raw)
        logger.info(f"Message from user {user.id}: {redacted[:80]}")

        await storage.append_message(user.id, 'user', redacted)

        response = await self.agent.get_response(user_message=redacted, user_id=user.id)

        await storage.append_message(user.id, 'assistant', response)
        await update.message.reply_text(response, parse_mode='Markdown')

    # -----------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------
    def _format_analysis_result(self, analysis: dict, recommendations: list) -> str:
        text = "✨ *Análise da Sua Pele* ✨\n\n"
        text += f"🎨 *Tom de Pele:* {analysis.get('skin_tone', 'N/D')}\n"
        text += f"💧 *Tipo de Pele:* {analysis.get('skin_type', 'N/D')}\n"
        if analysis.get('undertone'):
            text += f"🔸 *Subtom:* {analysis.get('undertone')}\n"
        if analysis.get('concerns'):
            text += "\n*Concerns identificados:*\n"
            for concern in analysis.get('concerns', []):
                text += f"  • {concern}\n"

        text += "\n" + "=" * 30 + "\n"
        text += "💡 *Produtos Recomendados:*\n\n"
        for i, rec in enumerate(recommendations[:5], 1):
            text += f"{i}. *{rec['name']}*\n"
            text += f"   💰 R$ {rec['price']}\n"
            text += f"   📝 {rec['description'][:80]}...\n\n"
        text += "\n💬 Quer mais detalhes sobre algum produto?"
        return text


async def _post_init(application):
    # Scheduler must start inside the asyncio loop that run_polling creates.
    start_scheduler()


async def _post_shutdown(application):
    stop_scheduler()


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        print("❌ Erro: TELEGRAM_BOT_TOKEN não configurado em .env / .env.local")
        return

    init_db()

    bot = BeautyBibleBot()
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("perfil", bot.profile_command))
    application.add_handler(CommandHandler("apagar_meus_dados", bot.delete_data_command))
    application.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    logger.info("🤖 BB (Beauty Bible) iniciando...")
    print("🤖 BB iniciada! Pressione Ctrl+C para parar")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
