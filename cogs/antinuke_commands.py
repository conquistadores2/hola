"""
Comandos slash para manejar el antinuke:

/whitelist add|remove|list        -> quién queda EXENTO de castigos
/antinukeadmin add|remove|list    -> quién puede administrar el antinuke
/antinuke setup|settings|punishment|module -> configuración general

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

import discord
from discord import app_commands
from discord.ext import commands

from utils import database

MODULE_CHOICES = [
    "channel_delete", "channel_create", "role_delete", "role_create",
    "ban", "kick", "webhook_create", "bot_add", "dangerous_role",
    "guild_update", "emoji_delete",
]


class OwnerOnlyError(app_commands.CheckFailure):
    pass


class AdminOnlyError(app_commands.CheckFailure):
    pass


def _is_owner(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    config = database.get_config(interaction.guild_id)
    return (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.id == config.get("owner_id")
    )


def _is_admin(interaction: discord.Interaction) -> bool:
    if _is_owner(interaction):
        return True
    if interaction.guild is None:
        return False
    config = database.get_config(interaction.guild_id)
    return interaction.user.id in config.get("admins", [])


def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise OwnerOnlyError("Este comando solo funciona dentro de un servidor.")
        if not _is_owner(interaction):
            raise OwnerOnlyError("Solo el dueño del servidor puede usar este comando.")
        return True
    return app_commands.check(predicate)


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise AdminOnlyError("Este comando solo funciona dentro de un servidor.")
        if not _is_admin(interaction):
            raise AdminOnlyError("Necesitas ser admin del antinuke (o dueño del servidor) para usar esto.")
        return True
    return app_commands.check(predicate)


# ------------------------------------------------------------------ #
# /whitelist
# ------------------------------------------------------------------ #
class WhitelistGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="whitelist", description="Gestiona quién queda exento del antinuke")

    @app_commands.command(name="add", description="Añade a alguien a la whitelist del antinuke")
    @app_commands.describe(usuario="Usuario que quedará exento de los castigos del antinuke")
    @admin_only()
    async def add(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = database.get_config(interaction.guild_id)
        if usuario.id in config["whitelist"]:
            await interaction.response.send_message(f"{usuario.mention} ya está en la whitelist.", ephemeral=True)
            return
        config["whitelist"].append(usuario.id)
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(
            f"✅ {usuario.mention} añadido a la whitelist. Ya no será castigado por el antinuke.",
            ephemeral=True,
        )

    @app_commands.command(name="remove", description="Quita a alguien de la whitelist del antinuke")
    @app_commands.describe(usuario="Usuario a quitar de la whitelist")
    @admin_only()
    async def remove(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = database.get_config(interaction.guild_id)
        if usuario.id not in config["whitelist"]:
            await interaction.response.send_message(f"{usuario.mention} no está en la whitelist.", ephemeral=True)
            return
        config["whitelist"].remove(usuario.id)
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(f"✅ {usuario.mention} eliminado de la whitelist.", ephemeral=True)

    @app_commands.command(name="list", description="Muestra la whitelist actual del antinuke")
    async def list_(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
            return
        config = database.get_config(interaction.guild_id)
        if not config["whitelist"]:
            await interaction.response.send_message("La whitelist está vacía.", ephemeral=True)
            return
        mentions = "\n".join(f"• <@{uid}>" for uid in config["whitelist"])
        embed = discord.Embed(title="📋 Whitelist del antinuke", description=mentions, color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------------------------------------------ #
# /antinukeadmin
# ------------------------------------------------------------------ #
class AdminGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="antinukeadmin", description="Gestiona quién administra el antinuke")

    @app_commands.command(name="add", description="Da permisos de administrador del antinuke a alguien")
    @app_commands.describe(usuario="Usuario que podrá manejar whitelist y configuración del antinuke")
    @owner_only()
    async def add(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = database.get_config(interaction.guild_id)
        if usuario.id in config["admins"]:
            await interaction.response.send_message(f"{usuario.mention} ya es admin del antinuke.", ephemeral=True)
            return
        config["admins"].append(usuario.id)
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(
            f"✅ {usuario.mention} ahora es admin del antinuke (puede manejar whitelist y ajustes).",
            ephemeral=True,
        )

    @app_commands.command(name="remove", description="Quita permisos de administrador del antinuke")
    @app_commands.describe(usuario="Usuario al que se le quitará el rol de admin del antinuke")
    @owner_only()
    async def remove(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = database.get_config(interaction.guild_id)
        if usuario.id not in config["admins"]:
            await interaction.response.send_message(f"{usuario.mention} no es admin del antinuke.", ephemeral=True)
            return
        config["admins"].remove(usuario.id)
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(f"✅ {usuario.mention} ya no es admin del antinuke.", ephemeral=True)

    @app_commands.command(name="list", description="Muestra los admins del antinuke")
    async def list_(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
            return
        config = database.get_config(interaction.guild_id)
        if not config["admins"]:
            await interaction.response.send_message("Todavía no hay admins del antinuke configurados.", ephemeral=True)
            return
        mentions = "\n".join(f"• <@{uid}>" for uid in config["admins"])
        embed = discord.Embed(title="📋 Admins del antinuke", description=mentions, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------------------------------------------ #
# /antinuke (configuración general)
# ------------------------------------------------------------------ #
class AntinukeGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="antinuke", description="Configuración general del sistema antinuke")

    @app_commands.command(name="setup", description="Configura el canal donde el antinuke enviará sus alertas")
    @app_commands.describe(canal="Canal de texto donde se enviarán los logs del antinuke")
    @owner_only()
    async def setup_cmd(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        config = database.get_config(interaction.guild_id)
        config["log_channel"] = canal.id
        if config.get("owner_id") is None:
            config["owner_id"] = interaction.guild.owner_id
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(f"✅ Canal de logs configurado en {canal.mention}.", ephemeral=True)

    @app_commands.command(name="punishment", description="Define el castigo por defecto del antinuke")
    @app_commands.describe(tipo="Qué hacer con quien dispare el antinuke")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Ban (expulsión permanente)", value="ban"),
        app_commands.Choice(name="Kick (expulsión simple)", value="kick"),
        app_commands.Choice(name="Strip (solo le quita todos los roles)", value="strip"),
    ])
    @admin_only()
    async def punishment_cmd(self, interaction: discord.Interaction, tipo: app_commands.Choice[str]) -> None:
        config = database.get_config(interaction.guild_id)
        config["punishment"] = tipo.value
        database.save_config(interaction.guild_id, config)
        await interaction.response.send_message(f"✅ Castigo por defecto cambiado a **{tipo.value}**.", ephemeral=True)

    @app_commands.command(name="module", description="Activa o desactiva un módulo de protección del antinuke")
    @app_commands.describe(modulo="Módulo a modificar", estado="Activado o desactivado")
    @app_commands.choices(modulo=[app_commands.Choice(name=m, value=m) for m in MODULE_CHOICES])
    @admin_only()
    async def module_cmd(
        self, interaction: discord.Interaction, modulo: app_commands.Choice[str], estado: bool,
    ) -> None:
        config = database.get_config(interaction.guild_id)
        config["modules"][modulo.value] = estado
        database.save_config(interaction.guild_id, config)
        emoji = "🟢" if estado else "🔴"
        await interaction.response.send_message(
            f"{emoji} Módulo `{modulo.value}` {'activado' if estado else 'desactivado'}.", ephemeral=True,
        )

    @app_commands.command(name="settings", description="Muestra la configuración actual del antinuke")
    async def settings_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
            return
        config = database.get_config(interaction.guild_id)

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

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(WhitelistGroup())
    bot.tree.add_command(AdminGroup())
    bot.tree.add_command(AntinukeGroup())
