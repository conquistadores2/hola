"""
Motor del antinuke: escucha los eventos "peligrosos" de Discord, revisa
quién los hizo (vía audit log), y si esa persona no está en la whitelist
ni es admin/dueño del antinuke, la castiga automáticamente.

Cosas importantes de diseño (léelas antes de tocar el código):

1. NO se confía en el permiso "Administrator" de Discord. Ese es
   justamente el punto de un antinuke: si a alguien le dieron admin
   (o le robaron la cuenta), igual se le castiga a menos que esté en
   la whitelist o sea admin del antinuke. Esto es intencional.

2. Casi todos los eventos de discord.py NO dicen quién ejecutó la
   acción (ej: on_guild_channel_delete solo te da el canal). Por eso
   se consulta el audit log (`guild.audit_logs`) justo después del
   evento para encontrar al responsable. Esto requiere el permiso
   "Ver registro de auditoría" (View Audit Log) para el bot.

3. Se usa un sistema de "umbral" (threshold): por ejemplo, borrar 1
   canal no dispara nada, pero borrar 2 en 8 segundos sí. Esto evita
   falsos positivos por una sola eliminación legítima, pero corta
   una racha de nuke casi de inmediato. Para acciones muy graves
   (dar un rol con permisos peligrosos, añadir un bot no autorizado,
   cambiar el nombre/ícono del server) el umbral es de 1, o sea que
   actúa al instante.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

import discord
from discord.ext import commands

from utils import database

log = logging.getLogger("antinuke")

# Permisos que, si se le dan a un rol o se otorgan a un miembro,
# se consideran peligrosos y disparan el antinuke de inmediato.
DANGEROUS_PERMS = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_expressions",
    "mention_everyone",
    "moderate_members",
)

# (límite de eventos, ventana en segundos) por tipo de acción.
THRESHOLDS: dict[str, tuple[int, int]] = {
    "channel_delete": (2, 8),
    "channel_create": (3, 8),
    "role_delete": (2, 8),
    "role_create": (3, 8),
    "ban": (2, 10),
    "kick": (2, 10),
    "webhook_create": (1, 5),
    "emoji_delete": (3, 10),
}

# Cuánto esperar (segundos) a que el audit log de Discord se actualice
# antes de leerlo. Sin esto, a veces se lee el log ANTES de que la
# entrada nueva aparezca y no se encuentra al ejecutor.
AUDIT_LOG_DELAY = 1.2
AUDIT_LOG_MAX_AGE = 8  # ignorar entradas de audit log más viejas que esto


def _role_is_dangerous(role: discord.Role) -> bool:
    perms = role.permissions
    return any(getattr(perms, perm, False) for perm in DANGEROUS_PERMS)


class Tracker:
    """Cuenta cuántas veces un usuario disparó una acción en una ventana de tiempo."""

    def __init__(self) -> None:
        self._events: dict[tuple[int, int, str], list[float]] = defaultdict(list)

    def hit(self, guild_id: int, user_id: int, action: str, limit: int, window: int) -> bool:
        key = (guild_id, user_id, action)
        now = time.time()
        bucket = [t for t in self._events[key] if now - t < window]
        bucket.append(now)
        self._events[key] = bucket
        return len(bucket) >= limit


def is_exempt(guild: discord.Guild, config: dict, user_id: int) -> bool:
    """True si el usuario NO debe ser castigado (dueño, admin, whitelist o el propio bot)."""
    if user_id == guild.owner_id:
        return True
    if user_id == config.get("owner_id"):
        return True
    if user_id in config.get("admins", []):
        return True
    if user_id in config.get("whitelist", []):
        return True
    me = guild.me
    if me is not None and user_id == me.id:
        return True
    return False


async def fetch_executor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int | None = None,
    max_age: int = AUDIT_LOG_MAX_AGE,
):
    """Busca en el audit log quién ejecutó una acción reciente. Devuelve un User/Member o None."""
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return None

    await asyncio.sleep(AUDIT_LOG_DELAY)

    try:
        async for entry in guild.audit_logs(limit=8, action=action):
            age = (discord.utils.utcnow() - entry.created_at).total_seconds()
            if age > max_age:
                return None
            if target_id is not None:
                target = entry.target
                tid = getattr(target, "id", target)
                if tid != target_id:
                    continue
            return entry.user
    except discord.Forbidden:
        return None
    return None


class AntiNukeEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tracker = Tracker()

    # ------------------------------------------------------------------ #
    # Núcleo: evaluar umbral y castigar si corresponde
    # ------------------------------------------------------------------ #
    async def _handle(
        self,
        guild: discord.Guild,
        action_name: str,
        executor: discord.abc.User | None,
        reason: str,
    ) -> None:
        if executor is None:
            return

        config = database.get_config(guild.id)
        if not config["modules"].get(action_name, True):
            return
        if is_exempt(guild, config, executor.id):
            return

        limit, window = THRESHOLDS.get(action_name, (1, 5))
        triggered = self.tracker.hit(guild.id, executor.id, action_name, limit, window)
        if not triggered:
            return

        await self._punish(guild, executor, reason, config)

    async def _punish(
        self,
        guild: discord.Guild,
        executor: discord.abc.User,
        reason: str,
        config: dict,
    ) -> None:
        punishment = config.get("punishment", "ban")
        member = guild.get_member(executor.id)

        if member is not None:
            try:
                await member.edit(roles=[], reason=f"[AntiNuke] {reason}")
            except discord.HTTPException:
                pass

        try:
            if punishment == "ban":
                await guild.ban(
                    discord.Object(id=executor.id),
                    reason=f"[AntiNuke] {reason}",
                    delete_message_seconds=0,
                )
            elif punishment == "kick" and member is not None:
                await guild.kick(member, reason=f"[AntiNuke] {reason}")
            # si punishment == "strip", ya alcanzó con quitarle los roles arriba
        except discord.Forbidden:
            log.warning(
                "Sin permisos suficientes para castigar a %s en %s (%s)",
                executor.id, guild.id, guild.name,
            )
        except discord.HTTPException as exc:
            log.warning("Fallo al castigar a %s: %s", executor.id, exc)

        await self._log(guild, executor, reason, config)

    async def _log(
        self,
        guild: discord.Guild,
        executor: discord.abc.User,
        reason: str,
        config: dict,
    ) -> None:
        channel_id = config.get("log_channel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return

        embed = discord.Embed(
            title="🛡️ Antinuke: acción bloqueada",
            description=reason,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Usuario", value=f"{executor} (`{executor.id}`)", inline=False)
        embed.add_field(name="Castigo aplicado", value=config.get("punishment", "ban"), inline=True)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    # Canales
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        executor = await fetch_executor(channel.guild, discord.AuditLogAction.channel_delete)
        await self._handle(channel.guild, "channel_delete", executor, f"Eliminó el canal **#{channel.name}**")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        executor = await fetch_executor(channel.guild, discord.AuditLogAction.channel_create)
        await self._handle(
            channel.guild, "channel_create", executor,
            f"Creó varios canales muy rápido (último: **#{channel.name}**)",
        )

    # ------------------------------------------------------------------ #
    # Roles
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        executor = await fetch_executor(role.guild, discord.AuditLogAction.role_delete)
        await self._handle(role.guild, "role_delete", executor, f"Eliminó el rol **@{role.name}**")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        executor = await fetch_executor(role.guild, discord.AuditLogAction.role_create)
        await self._handle(
            role.guild, "role_create", executor,
            f"Creó varios roles muy rápido (último: **@{role.name}**)",
        )

    # ------------------------------------------------------------------ #
    # Baneos / expulsiones
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User) -> None:
        executor = await fetch_executor(guild, discord.AuditLogAction.ban, target_id=user.id)
        await self._handle(guild, "ban", executor, f"Baneó a **{user}** (`{user.id}`)")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        # on_member_remove también se dispara cuando alguien se va solo,
        # así que confirmamos con el audit log que de verdad fue un kick.
        executor = await fetch_executor(
            member.guild, discord.AuditLogAction.kick, target_id=member.id, max_age=5,
        )
        if executor is None:
            return
        await self._handle(member.guild, "kick", executor, f"Expulsó a **{member}** (`{member.id}`)")

    # ------------------------------------------------------------------ #
    # Webhooks (vector clásico de spam/raid)
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        executor = await fetch_executor(channel.guild, discord.AuditLogAction.webhook_create)
        if executor is None:
            return
        await self._handle(
            channel.guild, "webhook_create", executor,
            f"Creó un webhook en **#{channel.name}**",
        )

    # ------------------------------------------------------------------ #
    # Bots añadidos sin autorización
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return

        guild = member.guild
        executor = await fetch_executor(guild, discord.AuditLogAction.bot_add, target_id=member.id)
        if executor is None:
            return

        config = database.get_config(guild.id)
        if not config["modules"].get("bot_add", True):
            return
        if is_exempt(guild, config, executor.id):
            return

        try:
            await guild.kick(member, reason="[AntiNuke] Bot añadido sin autorización")
        except discord.HTTPException:
            pass

        await self._punish(guild, executor, f"Añadió al bot **{member}** sin autorización", config)

    # ------------------------------------------------------------------ #
    # Rol peligroso otorgado a un miembro
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        added_roles = [r for r in after.roles if r not in before.roles]
        dangerous = [r for r in added_roles if _role_is_dangerous(r)]
        if not dangerous:
            return

        guild = after.guild
        config = database.get_config(guild.id)
        if not config["modules"].get("dangerous_role", True):
            return

        executor = await fetch_executor(guild, discord.AuditLogAction.member_role_update, target_id=after.id)
        if executor is None or is_exempt(guild, config, executor.id):
            return

        try:
            await after.remove_roles(*dangerous, reason="[AntiNuke] Rol peligroso otorgado sin autorización")
        except discord.HTTPException:
            pass

        role_names = ", ".join(f"@{r.name}" for r in dangerous)
        await self._punish(
            guild, executor,
            f"Le otorgó el rol peligroso **{role_names}** a **{after}** sin autorización",
            config,
        )

    # ------------------------------------------------------------------ #
    # Cambios en la configuración del servidor
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        changed = (
            before.name != after.name
            or before.icon != after.icon
            or before.vanity_url_code != after.vanity_url_code
        )
        if not changed:
            return

        config = database.get_config(after.id)
        if not config["modules"].get("guild_update", True):
            return

        executor = await fetch_executor(after, discord.AuditLogAction.guild_update)
        if executor is None or is_exempt(after, config, executor.id):
            return

        await self._punish(after, executor, "Modificó el nombre/ícono/vanity URL del servidor", config)

    # ------------------------------------------------------------------ #
    # Emojis
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self, guild: discord.Guild, before: list, after: list,
    ) -> None:
        if len(after) >= len(before):
            return  # no fue una eliminación

        executor = await fetch_executor(guild, discord.AuditLogAction.emoji_delete)
        await self._handle(guild, "emoji_delete", executor, "Eliminó emojis del servidor")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiNukeEvents(bot))
