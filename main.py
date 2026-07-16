"""
Bot de Discord con sistema antinuke.
Arranque: python main.py  (usa la variable de entorno DISCORD_TOKEN)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("antinuke")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    log.error("Falta la variable de entorno DISCORD_TOKEN. Configúrala antes de arrancar el bot.")
    sys.exit(1)

intents = discord.Intents.default()
intents.members = True       # necesario para on_member_join/remove/update
intents.moderation = True    # necesario para on_member_ban/unban
# No se activa message_content: todo funciona con slash commands.

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

EXTENSIONS = (
    "cogs.antinuke_events",
    "cogs.antinuke_commands",
)


@bot.event
async def on_ready() -> None:
    log.info("Conectado como %s (ID: %s)", bot.user, bot.user.id if bot.user else "?")
    try:
        synced = await bot.tree.sync()
        log.info("Sincronizados %d comandos slash.", len(synced))
    except discord.HTTPException as exc:
        log.exception("Error sincronizando comandos slash: %s", exc)

    print("=" * 50)
    print(f"  Bot activo: {bot.user}")
    print(f"  Servidores: {len(bot.guilds)}")
    print("  Antinuke listo. Ejecuta /antinuke setup en cada servidor.")
    print("=" * 50)


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    from utils import database
    database.ensure_owner(guild.id, guild.owner_id)
    log.info("Bot añadido al servidor '%s' (%s)", guild.name, guild.id)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CheckFailure):
        message = str(error) or "No tienes permiso para usar este comando."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"Espera {error.retry_after:.1f}s antes de volver a usar este comando."
    else:
        log.exception("Error inesperado en un comando de aplicación", exc_info=error)
        message = "Ocurrió un error inesperado ejecutando el comando."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


async def main() -> None:
    async with bot:
        for extension in EXTENSIONS:
            await bot.load_extension(extension)
            log.info("Extensión cargada: %s", extension)
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.LoginFailure:
        log.error("El DISCORD_TOKEN es inválido. Copia el token de nuevo desde el Developer Portal.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error(
            "Faltan intents privilegiados. Ve al Developer Portal -> tu app -> Bot "
            "y activa 'SERVER MEMBERS INTENT'."
        )
        sys.exit(1)
