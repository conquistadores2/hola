"""
Comandos híbridos para manejar el antinuke: cada comando funciona tanto
escrito con el prefijo de texto (ej: "!whitelist add @user") como con
comandos de barra (ej: "/whitelist add usuario:@user"). Es exactamente el
mismo código y la misma lógica en los dos casos (discord.py los llama
"hybrid commands").

/whitelist add|remove|list        -> quién queda EXENTO de castigos
/antinukeadmin add|remove|list    -> quién puede administrar el antinuke
/antinuke setup|settings|punishment|module -> configuración general
/help (alias de prefijo: "ayuda") -> lista todos los comandos

Jerarquía de permisos:
- Dueño del servidor (o quien quedó registrado como owner_id): puede
  todo, incluyendo nombrar/quitar admins del antinuke.
- Admin del antinuke: puede manejar la whitelist y la configuración,
  pero NO puede nombrar a otros admins (para que un admin comprometido
  no pueda meter cómplices).
- Whitelist: solo queda exento de los castigos del antinuke, no puede
  administrar nada.
"""
from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from utils import database

MODULE_CHOICES = [
    "channel_delete", "channel_create", "role_delete", "role_create",
    "ban", "kick", "webhook_create", "bot_add", "dangerous_role",
    "guild_update", "emoji_delete",
]

# typing.Literal con los valores válidos: discord.py lo convierte
# automáticamente en choices en el slash command y en un validador de
# texto en el comando con prefijo. Se arma dinámicamente para no repetir
# MODULE_CHOICES a mano.
PunishmentChoice = Literal["ban", "kick", "strip"]
ModuleChoice = Literal[tuple(MODULE_CHOICES)]


class OwnerOnlyError(commands.CheckFailure):
    pass


class AdminOnlyError(commands.CheckFailure):
    pass


def _is_owner(ctx: commands.Context) -> bool:
    config = database.get_config(ctx.guild.id)
    return (
        ctx.author.id == ctx.guild.owner_id
        or ctx.author.id == config.get("owner_id")
    )


def _is_admin(ctx: commands.Context) -> bool:
    if _is_owner(ctx):
        return True
    config = database.get_config(ctx.guild.id)
    return ctx.author.id in config.get("admins", [])


def owner_only():
    async def predicate(ctx: commands.Context) -> bool:
        if not _is_owner(ctx):
            raise OwnerOnlyError("Solo el dueño del servidor puede usar este comando.")
        return True
    return commands.check(predicate)


def admin_only():
    async def predicate(ctx: commands.Context) -> bool:
        if not _is_admin(ctx):
            raise AdminOnlyError("Necesitas ser admin del antinuke (o dueño del servidor) para usar esto.")
        return True
    return commands.check(predicate)


class AntiNukeCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        # Se aplica a TODOS los comandos de este cog sin importar si se
        # invocaron con prefijo o como slash (discord.py llama a cog_check
        # tanto desde Command.can_run() como desde
        # HybridAppCommand._check_can_run(), siempre antes que los checks
        # locales como owner_only()/admin_only() de abajo).
        if ctx.guild is None:
            raise commands.NoPrivateMessage("Este comando solo funciona dentro de un servidor.")
        return True

    # ------------------------------------------------------------------ #
    # whitelist
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(
        name="whitelist",
        description="Gestiona quién queda exento del antinuke",
        invoke_without_command=True,
    )
    async def whitelist(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix if ctx.interaction is None else "/"
        await ctx.send(f"Uso: `{prefix}whitelist add|remove|list`", ephemeral=True)

    @whitelist.command(name="add", description="Añade a alguien a la whitelist del antinuke")
    @app_commands.describe(usuario="Usuario que quedará exento de los castigos del antinuke")
    @admin_only()
    async def whitelist_add(self, ctx: commands.Context, usuario: discord.Member) -> None:
        config = database.get_config(ctx.guild.id)
        if usuario.id in config["whitelist"]:
            await ctx.send(f"{usuario.mention} ya está en la whitelist.", ephemeral=True)
            return
        config["whitelist"].append(usuario.id)
        database.save_config(ctx.guild.id, config)
        await ctx.send(
            f"✅ {usuario.mention} añadido a la whitelist. Ya no será castigado por el antinuke.",
            ephemeral=True,
        )

    @whitelist.command(name="remove", description="Quita a alguien de la whitelist del antinuke")
    @app_commands.describe(usuario="Usuario a quitar de la whitelist")
    @admin_only()
    async def whitelist_remove(self, ctx: commands.Context, usuario: discord.Member) -> None:
        config = database.get_config(ctx.guild.id)
        if usuario.id not in config["whitelist"]:
            await ctx.send(f"{usuario.mention} no está en la whitelist.", ephemeral=True)
            return
        config["whitelist"].remove(usuario.id)
        database.save_config(ctx.guild.id, config)
        await ctx.send(f"✅ {usuario.mention} eliminado de la whitelist.", ephemeral=True)

    @whitelist.command(name="list", description="Muestra la whitelist actual del antinuke")
    async def whitelist_list(self, ctx: commands.Context) -> None:
        config = database.get_config(ctx.guild.id)
        if not config["whitelist"]:
            await ctx.send("La whitelist está vacía.", ephemeral=True)
            return
        mentions = "\n".join(f"• <@{uid}>" for uid in config["whitelist"])
        embed = discord.Embed(title="📋 Whitelist del antinuke", description=mentions, color=discord.Color.green())
        await ctx.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # antinukeadmin
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(
        name="antinukeadmin",
        description="Gestiona quién administra el antinuke",
        invoke_without_command=True,
    )
    async def antinukeadmin(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix if ctx.interaction is None else "/"
        await ctx.send(f"Uso: `{prefix}antinukeadmin add|remove|list`", ephemeral=True)

    @antinukeadmin.command(name="add", description="Da permisos de administrador del antinuke a alguien")
    @app_commands.describe(usuario="Usuario que podrá manejar whitelist y configuración del antinuke")
    @owner_only()
    async def antinukeadmin_add(self, ctx: commands.Context, usuario: discord.Member) -> None:
        config = database.get_config(ctx.guild.id)
        if usuario.id in config["admins"]:
            await ctx.send(f"{usuario.mention} ya es admin del antinuke.", ephemeral=True)
            return
        config["admins"].append(usuario.id)
        database.save_config(ctx.guild.id, config)
        await ctx.send(
            f"✅ {usuario.mention} ahora es admin del antinuke (puede manejar whitelist y ajustes).",
            ephemeral=True,
        )

    @antinukeadmin.command(name="remove", description="Quita permisos de administrador del antinuke")
    @app_commands.describe(usuario="Usuario al que se le quitará el rol de admin del antinuke")
    @owner_only()
    async def antinukeadmin_remove(self, ctx: commands.Context, usuario: discord.Member) -> None:
        config = database.get_config(ctx.guild.id)
        if usuario.id not in config["admins"]:
            await ctx.send(f"{usuario.mention} no es admin del antinuke.", ephemeral=True)
            return
        config["admins"].remove(usuario.id)
        database.save_config(ctx.guild.id, config)
        await ctx.send(f"✅ {usuario.mention} ya no es admin del antinuke.", ephemeral=True)

    @antinukeadmin.command(name="list", description="Muestra los admins del antinuke")
    async def antinukeadmin_list(self, ctx: commands.Context) -> None:
        config = database.get_config(ctx.guild.id)
        if not config["admins"]:
            await ctx.send("Todavía no hay admins del antinuke configurados.", ephemeral=True)
            return
        mentions = "\n".join(f"• <@{uid}>" for uid in config["admins"])
        embed = discord.Embed(title="📋 Admins del antinuke", description=mentions, color=discord.Color.blue())
        await ctx.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # antinuke (configuración general)
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(
        name="antinuke",
        description="Configuración general del sistema antinuke",
        invoke_without_command=True,
    )
    async def antinuke(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix if ctx.interaction is None else "/"
        await ctx.send(f"Uso: `{prefix}antinuke setup|settings|punishment|module`", ephemeral=True)

    @antinuke.command(name="setup", description="Configura el canal donde el antinuke enviará sus alertas")
    @app_commands.describe(canal="Canal de texto donde se enviarán los logs del antinuke")
    @owner_only()
    async def antinuke_setup(self, ctx: commands.Context, canal: discord.TextChannel) -> None:
        config = database.get_config(ctx.guild.id)
        config["log_channel"] = canal.id
        if config.get("owner_id") is None:
            config["owner_id"] = ctx.guild.owner_id
        database.save_config(ctx.guild.id, config)
        await ctx.send(f"✅ Canal de logs configurado en {canal.mention}.", ephemeral=True)

    @antinuke.command(name="punishment", description="Define el castigo por defecto del antinuke")
    @app_commands.describe(tipo="Qué hacer con quien dispare el antinuke")
    @admin_only()
    async def antinuke_punishment(self, ctx: commands.Context, tipo: PunishmentChoice) -> None:
        config = database.get_config(ctx.guild.id)
        config["punishment"] = tipo
        database.save_config(ctx.guild.id, config)
        await ctx.send(f"✅ Castigo por defecto cambiado a **{tipo}**.", ephemeral=True)

    @antinuke.command(name="module", description="Activa o desactiva un módulo de protección del antinuke")
    @app_commands.describe(modulo="Módulo a modificar", estado="Activado o desactivado")
    @admin_only()
    async def antinuke_module(
        self, ctx: commands.Context, modulo: ModuleChoice, estado: bool,
    ) -> None:
        config = database.get_config(ctx.guild.id)
        config["modules"][modulo] = estado
        database.save_config(ctx.guild.id, config)
        emoji = "🟢" if estado else "🔴"
        await ctx.send(
            f"{emoji} Módulo `{modulo}` {'activado' if estado else 'desactivado'}.", ephemeral=True,
        )

    @antinuke.command(name="settings", description="Muestra la configuración actual del antinuke")
    async def antinuke_settings(self, ctx: commands.Context) -> None:
        config = database.get_config(ctx.guild.id)

        embed = discord.Embed(title="⚙️ Configuración del antinuke", color=discord.Color.blurple())
        owner_id = config.get("owner_id")
        embed.add_field(name="Dueño registrado", value=f"<@{owner_id}>" if owner_id else "No definido", inline=False)
        embed.add_field(name="Castigo", value=config.get("punishment", "ban"), inline=True)
        log_ch = config.get("log_channel")
        embed.add_field(name="Canal de logs", value=f"<#{log_ch}>" if log_ch else "No configurado", inline=True)

        admins = ", ".join(f"<@{a}>" for a in config.get("admins", [])) or "Ninguno"
        whitelist = ", ".join(f"<@{w}>" for w in config.get("whitelist", [])) or "Ninguno"
        embed.add_field(name="Admins del antinuke", value=admins, inline=False)
        embed.add_field(name="Whitelist", value=whitelist, inline=False)

        modules = config.get("modules", {})
        mod_text = "\n".join(f"{'🟢' if v else '🔴'} `{k}`" for k, v in modules.items())
        embed.add_field(name="Módulos", value=mod_text or "N/A", inline=False)

        await ctx.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # help (alias de prefijo: "ayuda")
    # ------------------------------------------------------------------ #
    @commands.hybrid_command(name="help", aliases=["ayuda"], description="Muestra los comandos disponibles del antinuke")
    async def help_cmd(self, ctx: commands.Context) -> None:
        prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else "!"
        embed = discord.Embed(
            title="🛡️ Comandos del antinuke",
            description=f"Cada comando funciona como slash (`/comando`) o con el prefijo `{prefix}` (ej: `{prefix}whitelist list`).",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="whitelist add|remove|list",
            value="Gestiona quién queda exento de los castigos del antinuke. *(admin o dueño)*",
            inline=False,
        )
        embed.add_field(
            name="antinukeadmin add|remove|list",
            value="Gestiona quién puede administrar el antinuke. *(solo dueño)*",
            inline=False,
        )
        embed.add_field(
            name="antinuke setup|settings|punishment|module",
            value="Canal de logs, castigo por defecto y módulos de protección activos.",
            inline=False,
        )
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiNukeCommands(bot))
