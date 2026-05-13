"""
Beauty Bible Agent - Main Entry Point
Bot Telegram da BB (consultora pessoal de beleza) com memória persistente em SQLCipher.
"""

import asyncio
import logging
import os
from html import escape as html_escape
from pathlib import Path

from telegram import Update
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.skin_analyzer import SkinAnalyzer
from src.product_db import ProductDatabase
from src.agent import BeautyAdvisorAgent
from src.chat_pacing import keep_typing, send_chunked
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
        # Per-user in-flight response task — lets a new message cancel the
        # pending reply instead of letting both run and arrive out of order.
        self._response_tasks: dict[int, asyncio.Task] = {}

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
    # Photo handler — analyze, persist, then hand off to BB for warm reply
    # -----------------------------------------------------------
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat_id = update.effective_chat.id
        await storage.ensure_user(user.id, user.username, user.first_name)
        logger.info(f"Received photo from user {user.id}")

        processing_msg = await update.message.reply_text(
            "📸 Tô olhando aqui com carinho..."
        )

        photo_path: Path | None = None
        analyzed = False
        try:
            photo = update.message.photo[-1]  # highest res
            photo_file = await context.bot.get_file(photo.file_id)
            photos_dir = Path(__file__).parent / 'data' / 'user_photos'
            photos_dir.mkdir(parents=True, exist_ok=True)

            photo_path = photos_dir / f"{user.id}_{photo.file_id}.jpg"
            await photo_file.download_to_drive(photo_path)

            # Hash before analysis (stable even after deletion)
            phash = hash_photo(photo_path.read_bytes())

            analysis = await self.skin_analyzer.analyze(photo_path)

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
            analyzed = True

        except Exception as e:
            logger.exception(f"Error analyzing photo: {e}")
            try:
                await processing_msg.edit_text(
                    "❌ Não consegui analisar essa foto. Tenta uma com mais luz natural? 💛"
                )
            except Exception:
                pass
        finally:
            # Delete the raw photo regardless — only the structured analysis + hash remain.
            if photo_path and photo_path.exists():
                try:
                    photo_path.unlink()
                except OSError as e:
                    logger.warning(f"Could not delete {photo_path}: {e}")

        if not analyzed:
            return

        # Hand off to BB for warm presentation. Delete the processing notice so
        # the chunked bubbles arrive cleanly without the "tô olhando" line above.
        try:
            await processing_msg.delete()
        except Exception:
            pass

        # Cancel any pending text-handler reply — photo trumps prior chatter.
        prev = self._response_tasks.get(user.id)
        if prev and not prev.done():
            prev.cancel()
            try:
                await prev
            except (asyncio.CancelledError, Exception):
                pass

        task = asyncio.create_task(self._present_analysis_flow(user.id, chat_id, context))
        self._response_tasks[user.id] = task

    async def _present_analysis_flow(
        self,
        user_id: int,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """LLM-driven warm presentation of the just-saved skin profile."""
        stop = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(context.bot, chat_id, stop))
        try:
            response, sources = await self.agent.present_analysis(user_id)
        except asyncio.CancelledError:
            logger.info(f"Analysis presentation cancelled for user {user_id}")
            raise
        except Exception as e:
            logger.exception(f"present_analysis failed for {user_id}: {e}")
            stop.set()
            await typing_task
            try:
                await context.bot.send_message(
                    chat_id,
                    "Consegui ver sua análise, mas travei aqui pra te contar. Tenta de novo? 💛",
                )
            except Exception:
                pass
            return
        finally:
            stop.set()
            try:
                await typing_task
            except Exception:
                pass

        try:
            await storage.append_message(user_id, 'assistant', response)
        except Exception:
            logger.exception(f"Failed to persist analysis presentation for {user_id}")

        try:
            await send_chunked(context.bot, chat_id, response, sources=sources)
        except asyncio.CancelledError:
            logger.info(f"Analysis presentation chunks cancelled for user {user_id}")
            raise
        except Exception as e:
            logger.exception(f"send_chunked (analysis) failed for {user_id}: {e}")

    # -----------------------------------------------------------
    # Text handler — chunked reply with typing simulation
    # -----------------------------------------------------------
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await storage.ensure_user(user.id, user.username, user.first_name)

        raw = update.message.text
        redacted = redact_pii(raw)
        logger.info(f"Message from user {user.id}: {redacted[:80]}")

        await storage.append_message(user.id, 'user', redacted)

        # If a previous reply is still streaming chunks, cancel it so the new
        # message doesn't get its response interleaved with the old one.
        prev = self._response_tasks.get(user.id)
        if prev and not prev.done():
            prev.cancel()
            try:
                await prev
            except (asyncio.CancelledError, Exception):
                pass

        # Fire-and-forget: handler returns quickly, response streams in background.
        task = asyncio.create_task(
            self._generate_and_send(user.id, update.effective_chat.id, redacted, context),
        )
        self._response_tasks[user.id] = task

    async def _generate_and_send(
        self,
        user_id: int,
        chat_id: int,
        user_message: str,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Run LLM generation with a typing pulse, then send the reply in chunks."""
        stop = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(context.bot, chat_id, stop))
        try:
            response, sources = await self.agent.get_response(
                user_message=user_message, user_id=user_id,
            )
        except asyncio.CancelledError:
            logger.info(f"Response generation cancelled for user {user_id}")
            raise
        except Exception as e:
            logger.exception(f"LLM call failed for user {user_id}: {e}")
            stop.set()
            await typing_task
            try:
                await context.bot.send_message(
                    chat_id, "Ops, deu ruim aqui do meu lado. Tenta de novo? 💛",
                )
            except Exception:
                pass
            return
        finally:
            stop.set()
            try:
                await typing_task
            except Exception:
                pass

        # Persist the assistant turn before sending so a crash mid-send doesn't
        # leave the user's message dangling in history without a reply on file.
        try:
            await storage.append_message(user_id, 'assistant', response)
        except Exception:
            logger.exception(f"Failed to persist assistant message for user {user_id}")

        try:
            await send_chunked(context.bot, chat_id, response, sources=sources)
        except asyncio.CancelledError:
            logger.info(f"Chunked send cancelled mid-stream for user {user_id}")
            raise
        except Exception as e:
            logger.exception(f"send_chunked failed for user {user_id}: {e}")

async def _post_init(application):
    # Scheduler must start inside the asyncio loop that run_polling creates.
    start_scheduler()


async def _post_shutdown(application):
    stop_scheduler()


async def _on_error(update, context):
    """Catch-all so handler failures are logged + user gets a friendly reply."""
    err = context.error

    # Conflict = old container still polling during a deploy overlap.
    # PTB retries the polling loop internally, self-heals in ~30s. Not actionable.
    if isinstance(err, Conflict):
        logger.warning(f"Telegram getUpdates conflict (deploy overlap): {err}")
        return

    # Transient network blips: PTB's retry loop handles them. Just note in logs.
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"Transient network error: {type(err).__name__}: {err}")
        return

    # Anything else is genuinely unexpected — full stacktrace for diagnosis.
    logger.exception("Unhandled error in handler", exc_info=err)
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

    # drop_pending_updates: on startup, throw away updates that piled up during
    # the previous container's shutdown — avoids reprocessing the same message
    # twice when EasyPanel rolls the deploy.
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == '__main__':
    main()
