"""
Beauty Bible Agent - Main Entry Point
Bot Telegram da BB (consultora pessoal de beleza) com memória persistente em SQLCipher.
"""

import os
import logging
from pathlib import Path

from html import escape as html_escape

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
✨ <b>Oi, eu sou a BB!</b> ✨

Sua consultora pessoal de beleza. Posso te ajudar a:

🔍 <b>Analisar sua pele</b> — Envie uma foto do seu rosto e eu identifico seu tom, tipo e necessidades

💄 <b>Recomendar produtos</b> — Com base na análise, sugiro o que combina com você

🧴 <b>Montar sua rotina</b> — Cuidado personalizado, manhã e noite

📦 <b>Tirar dúvidas</b> — Sobre ingredientes, marcas, técnicas

Como posso te ajudar hoje?

<i>Seus dados são protegidos. Use /apagar_meus_dados a qualquer momento.</i>
"""
        await update.message.reply_text(welcome_message, parse_mode='HTML')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📚 <b>Comandos disponíveis:</b>

/start — Iniciar conversa
/help — Ver esta ajuda
/perfil — Ver minha análise de pele atual
/apagar_meus_dados — Apagar tudo o que a BB sabe sobre você

💡 <b>Dicas:</b>
- Para análise de pele, mande uma foto com boa luz
- Pode perguntar sobre ingredientes específicos
- A BB lembra das nossas conversas anteriores
"""
        await update.message.reply_text(help_text, parse_mode='HTML')

    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        profile = await storage.get_profile(user.id)
        if not profile:
            await update.message.reply_text(
                "Ainda não temos sua análise! Me envie uma foto pra começarmos 📸"
            )
            return
        text = "✨ <b>Seu Perfil Atual</b> ✨\n\n"
        text += f"🎨 <b>Tom:</b> {html_escape(profile.get('skin_tone_name') or 'N/D')}\n"
        text += f"💧 <b>Tipo:</b> {html_escape(profile.get('skin_type') or 'N/D')}\n"
        text += f"🔸 <b>Subtom:</b> {html_escape(profile.get('undertone') or 'N/D')}\n"
        concerns = profile.get('concerns', [])
        if concerns:
            text += "\n<b>Concerns:</b>\n" + "\n".join(
                f"  • {html_escape(c)}" for c in concerns
            )
        text += f"\n\n<i>Atualizado em {html_escape(str(profile.get('updated_at')))}</i>"
        await update.message.reply_text(text, parse_mode='HTML')

    async def delete_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """LGPD Art. 18 — right to be forgotten."""
        user = update.effective_user
        counts = await storage.delete_user_data(user.id)
        total = sum(counts.values())
        await update.message.reply_text(
            f"🗑️ <b>Pronto.</b> Apaguei tudo o que tínhamos sobre você ({total} registros).\n\n"
            f"Se quiser voltar, é só me mandar um /start. 💛",
            parse_mode='HTML',
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
            await processing_msg.edit_text(result_text, parse_mode='HTML')

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
        # No parse_mode: LLM responses are free-form and may contain unbalanced
        # markdown that would crash the send. Plain text is safer.
        await update.message.reply_text(response)

    # -----------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------
    def _format_analysis_result(self, analysis: dict, recommendations: list) -> str:
        e = html_escape
        text = "✨ <b>Análise da Sua Pele</b> ✨\n\n"
        text += f"🎨 <b>Tom de Pele:</b> {e(str(analysis.get('skin_tone', 'N/D')))}\n"
        text += f"💧 <b>Tipo de Pele:</b> {e(str(analysis.get('skin_type', 'N/D')))}\n"
        if analysis.get('undertone'):
            text += f"🔸 <b>Subtom:</b> {e(str(analysis.get('undertone')))}\n"
        if analysis.get('concerns'):
            text += "\n<b>Concerns identificados:</b>\n"
            for concern in analysis.get('concerns', []):
                text += f"  • {e(str(concern))}\n"

        text += "\n" + "=" * 30 + "\n"
        text += "💡 <b>Produtos Recomendados:</b>\n\n"
        for i, rec in enumerate(recommendations[:5], 1):
            text += f"{i}. <b>{e(rec['name'])}</b>\n"
            text += f"   💰 R$ {rec['price']}\n"
            text += f"   📝 {e(rec['description'][:80])}...\n\n"
        text += "\n💬 Quer mais detalhes sobre algum produto?"
        return text


async def _post_init(application):
    # Scheduler must start inside the asyncio loop that run_polling creates.
    start_scheduler()


async def _post_shutdown(application):
    stop_scheduler()


async def _on_error(update, context):
    """Catch-all so handler failures are logged + user gets a friendly reply."""
    logger.exception("Unhandled error in handler", exc_info=context.error)
    try:
        if update and getattr(update, 'effective_message', None):
            await update.effective_message.reply_text(
                "Ops, tive um probleminha aqui. Pode tentar de novo? 💛"
            )
    except Exception:
        logger.exception("Failed to send error message to user")


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
    application.add_error_handler(_on_error)

    logger.info("🤖 BB (Beauty Bible) iniciando...")
    print("🤖 BB iniciada! Pressione Ctrl+C para parar")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
