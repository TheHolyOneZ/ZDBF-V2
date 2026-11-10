# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from ...ui import BaseView, FormField, FormModal, Glyph, Status, button, cards, row
from .actions import ACTION_TYPES, CUSTOM, MAX_ACTIONS, ActionField, action_problems, summarize
from .engine import VARIABLE_HELP, Automation
from .templates import Param, Template

if TYPE_CHECKING:
    from .cog import Automations

TEXT_KINDS = ("text", "textarea", "number", "json")


def _fmt(param: Param, value: Any) -> str:
    if value in (None, "", []):
        return "*not set*"
    match param.kind:
        case "channel":
            return f"<#{value}>"
        case "role":
            return f"<@&{value}>"
        case "roles":
            return ", ".join(f"<@&{v}>" for v in value) if isinstance(value, list) else str(value)
        case "bool":
            return "on" if value else "off"
        case "actions":
            return f"{len(value)} action(s)" if isinstance(value, list) else "*not set*"
        case "json":
            return f"`{cards.truncate(json.dumps(value) if not isinstance(value, str) else value, 80)}`"
        case _:
            return cards.truncate(str(value).replace("\n", " "), 90)


def coerce(param: Param | ActionField, raw: str) -> tuple[Any, str | None]:
    raw = raw.strip()
    if not raw:
        return None, None
    match param.kind:
        case "number":
            try:
                value = float(raw)
            except ValueError:
                return None, f"**{param.label}** must be a number"
            return (int(value) if value.is_integer() else value), None
        case "json":
            try:
                return json.loads(raw), None
            except json.JSONDecodeError as exc:
                return None, f"**{param.label}** is not valid JSON ({exc.msg})"
        case _:
            return raw, None


def _fmt_field(f: ActionField, value: Any) -> str:
    if value in (None, "", []):
        return "*not set*" if f.kind != "channel" else "*event channel*"
    match f.kind:
        case "channel":
            return f"<#{value}>"
        case "role":
            return f"<@&{value}>"
        case "bool":
            return "on" if value else "off"
        case "automation":
            return f"`{value}`"
        case "json":
            return f"`{cards.truncate(json.dumps(value) if not isinstance(value, str) else value, 80)}`"
    return cards.truncate(str(value).replace("\n", " "), 90)


def _choice_labels(p: Param) -> dict[str, str]:
    if p.key == "trigger":
        from .actions import TRIGGERS

        return {k: v[0] for k, v in TRIGGERS.items()}
    if p.key == "match":
        return {"any": "Any message", "contains": "Contains the keyword", "exact": "Is exactly the keyword",
                "starts_with": "Starts with the keyword", "regex": "Matches a regular expression"}
    return {}


class BuilderView(BaseView):
    def __init__(self, cog: Automations, template: Template, *, author_id: int,
                 existing: Automation | None = None, guild_id: int | None = None) -> None:
        super().__init__(author_id=author_id, timeout=900)
        self.cog = cog
        self.template = template
        self.existing = existing
        self.guild_id = guild_id or (existing.guild_id if existing else None)
        self.mode = "main"
        self.selected = 0
        self.name = existing.name if existing else template.name
        self.config: dict[str, Any] = json.loads(json.dumps(existing.config)) if existing else template.defaults()
        if any(p.kind == "actions" for p in template.params):
            self.config.setdefault("actions", [])
        self.errors: list[str] = []
        self.done: Automation | None = None

    def _summary(self) -> str:
        lines = [f"**Name** · {self.name}"]
        for p in self.template.visible(self.config):
            mark = Status.ERROR if p.required and self.config.get(p.key) in (None, "", []) else Glyph.BULLET
            lines.append(f"{mark} **{p.label}**  {_fmt(p, self.config.get(p.key))}")
        return "\n".join(lines)

    def build(self) -> None:
        self.clear_items()
        if self.done is not None:
            self.add_item(self.cog.automation_card(self.done, title_prefix="Saved: "))
            return
        if self.mode == "actions":
            self.add_item(self._actions_page())
            return
        if self.mode == "action":
            self.add_item(self._action_page())
            return
        t = self.template
        visible = t.visible(self.config)
        box = cards.card(
            ("Edit " if self.existing else "New ") + t.name,
            t.description,
            cards.sep(),
            self._summary(),
            ("\n".join(f"{Status.WARN} {e}" for e in self.errors)) if self.errors else None,
            accent="error" if self.errors else "primary",
        )
        box.add_item(cards.sep())
        for p in visible:
            if p.kind == "channel":
                box.add_item(row(self._channel_select(p)))
            elif p.kind in ("role", "roles"):
                box.add_item(row(self._role_select(p)))
            elif p.kind == "choice":
                box.add_item(row(self._choice_select(p)))
        toggles = [self._toggle(p) for p in visible if p.kind == "bool"]
        if any(p.kind == "actions" for p in visible):
            toggles.insert(0, button(f"Edit actions ({len(self.config.get('actions') or [])})", self._open_actions,
                                     style=discord.ButtonStyle.primary))
        for i in range(0, len(toggles), 5):
            box.add_item(row(*toggles[i:i + 5]))
        text_params = [p for p in visible if p.kind in TEXT_KINDS]
        pages = [text_params[:4]] + [text_params[i:i + 5] for i in range(4, len(text_params), 5)]
        edit_buttons = [
            button("Edit name & texts" if i == 0 else f"More texts ({i + 1})", self._modal_opener(i, page), style=discord.ButtonStyle.primary)
            for i, page in enumerate(pages)
        ]
        missing = t.missing(self.config)
        controls = [
            *edit_buttons,
            button("Save" if self.existing else "Create", self._save,
                   style=discord.ButtonStyle.success, disabled=bool(missing)),
            button("Cancel", self._cancel),
        ]
        box.add_item(row(*controls[:5]))
        box.add_item(cards.footer("Required fields are marked with a red dot · changes are kept until you press "
                                  + ("Save" if self.existing else "Create")))
        self.add_item(box)

    def _channel_select(self, p: Param) -> ui.ChannelSelect[Any]:
        current = self.config.get(p.key)
        sel: ui.ChannelSelect[Any] = ui.ChannelSelect(
            placeholder=f"{p.label}{' *' if p.required else ''}", channel_types=list(p.channel_types),
            min_values=0, max_values=1,
            default_values=[discord.Object(int(current))] if current else [],
        )

        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.config[p.key] = sel.values[0].id if sel.values else None
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _role_select(self, p: Param) -> ui.RoleSelect[Any]:
        current = self.config.get(p.key)
        ids = current if isinstance(current, list) else ([current] if current else [])
        sel: ui.RoleSelect[Any] = ui.RoleSelect(
            placeholder=f"{p.label}{' *' if p.required else ''}", min_values=0,
            max_values=20 if p.kind == "roles" else 1,
            default_values=[discord.Object(int(i)) for i in ids][:20],
        )

        async def cb(interaction: discord.Interaction[Any]) -> None:
            ids = [r.id for r in sel.values]
            self.config[p.key] = ids if p.kind == "roles" else (ids[0] if ids else None)
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _choice_select(self, p: Param) -> ui.Select[Any]:
        current = self.config.get(p.key, p.default)
        labels = _choice_labels(p)
        sel: ui.Select[Any] = ui.Select(
            placeholder=p.label,
            options=[discord.SelectOption(label=labels.get(c, c.replace("_", " ").replace(",", " + "))[:100], value=c,
                                          default=c == current) for c in p.choices],
        )

        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.config[p.key] = sel.values[0]
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _toggle(self, p: Param) -> ui.Button[Any]:
        on = bool(self.config.get(p.key, p.default))

        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.config[p.key] = not bool(self.config.get(p.key, p.default))
            await self.refresh(interaction)

        return button(p.label[:80], cb,
                      style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary)

    def _modal_opener(self, index: int, params: list[Param]):
        async def cb(interaction: discord.Interaction[Any]) -> None:
            form: list[FormField] = []
            if index == 0:
                form.append(FormField("__name__", "Name", default=self.name, max_length=80))
            for p in params:
                value = self.config.get(p.key)
                text = json.dumps(value, ensure_ascii=False) if p.kind == "json" and not isinstance(value, str) else value
                form.append(FormField(
                    p.key, p.label, description=cards.truncate(p.description, 100) or None,
                    default=None if text is None else str(text)[:4000], required=p.required,
                    paragraph=p.kind in ("textarea", "json"), max_length=4000 if p.kind != "text" else 300,
                ))

            async def done(modal_interaction: discord.Interaction[Any], values: dict[str, str]) -> None:
                self.errors = []
                if values.get("__name__"):
                    self.name = values.pop("__name__")[:80]
                for p in params:
                    if p.key in values:
                        value, err = coerce(p, values[p.key])
                        if err:
                            self.errors.append(err)
                        else:
                            self.config[p.key] = value
                await self.refresh(modal_interaction)

            await interaction.response.send_modal(FormModal(f"{self.template.name} settings", form, done))

        return cb

    @property
    def actions(self) -> list[dict[str, Any]]:
        return self.config.setdefault("actions", [])

    async def _open_actions(self, interaction: discord.Interaction[Any]) -> None:
        self.mode = "actions"
        await self.refresh(interaction)

    def _actions_page(self) -> ui.Container[Any]:
        actions = self.actions
        lines = []
        for i, action in enumerate(actions, 1):
            mark = Status.ERROR if action_problems(action) else Glyph.BULLET
            lines.append(f"{mark} `{i:>2}.` {summarize(action)}")
        box = cards.card(
            f"Actions · {self.name}",
            "Actions run top to bottom each time the trigger fires.",
            cards.sep(),
            "\n".join(lines) if lines else "*No actions yet - add the first one below.*",
            f"-# Variables: {VARIABLE_HELP}",
            accent="primary",
        )
        if actions:
            pick: ui.Select[Any] = ui.Select(placeholder="Edit an action", options=[
                discord.SelectOption(label=f"{i}. {cards.truncate(summarize(a), 90)}"[:100], value=str(i - 1))
                for i, a in enumerate(actions, 1)])

            async def picked(interaction: discord.Interaction[Any]) -> None:
                self.selected = int(pick.values[0])
                self.mode = "action"
                await self.refresh(interaction)

            pick.callback = picked  # type: ignore[method-assign]
            box.add_item(row(pick))
        add: ui.Select[Any] = ui.Select(
            placeholder="Add an action" if len(actions) < MAX_ACTIONS else f"Limit of {MAX_ACTIONS} actions reached",
            disabled=len(actions) >= MAX_ACTIONS,
            options=[discord.SelectOption(label=t.name, value=t.id, description=cards.truncate(t.description, 100))
                     for t in ACTION_TYPES.values()])

        async def added(interaction: discord.Interaction[Any]) -> None:
            kind = ACTION_TYPES[add.values[0]]
            self.actions.append({"type": kind.id, **kind.defaults()})
            self.selected = len(self.actions) - 1
            self.mode = "action"
            await self.refresh(interaction)

        add.callback = added  # type: ignore[method-assign]
        box.add_item(row(add))

        async def back(interaction: discord.Interaction[Any]) -> None:
            self.mode = "main"
            await self.refresh(interaction)

        box.add_item(row(button(f"{Glyph.PREV} Back to settings", back)))
        return box

    def _action_page(self) -> ui.Container[Any]:
        actions = self.actions
        if not actions:
            self.mode = "actions"
            return self._actions_page()
        self.selected = max(0, min(self.selected, len(actions) - 1))
        action = actions[self.selected]
        kind = ACTION_TYPES.get(str(action.get("type")))
        if kind is None:
            actions.pop(self.selected)
            self.mode = "actions"
            return self._actions_page()
        problems = action_problems(action)
        lines = []
        for f in kind.fields:
            value = action.get(f.key)
            mark = Status.ERROR if f.required and value in (None, "", []) else Glyph.BULLET
            lines.append(f"{mark} **{f.label}**  {_fmt_field(f, value)}")
        box = cards.card(
            f"Action {self.selected + 1} of {len(actions)} · {kind.name}",
            kind.description,
            cards.sep(),
            "\n".join(lines) or "*No settings.*",
            "\n".join(f"{Status.WARN} {p}" for p in problems) if problems else None,
            accent="warning" if problems else "primary",
        )
        for f in kind.fields:
            if f.kind == "channel":
                box.add_item(row(self._action_channel(action, f)))
            elif f.kind == "role":
                box.add_item(row(self._action_role(action, f)))
            elif f.kind == "automation":
                box.add_item(row(self._action_automation(action, f)))
        texts = [f for f in kind.fields if f.kind in ("text", "textarea", "number", "json")]
        toggles = [self._action_toggle(action, f) for f in kind.fields if f.kind == "bool"]
        i = self.selected

        async def move(interaction: discord.Interaction[Any], delta: int) -> None:
            j = i + delta
            if 0 <= j < len(self.actions):
                self.actions[i], self.actions[j] = self.actions[j], self.actions[i]
                self.selected = j
            await self.refresh(interaction)

        async def up(interaction: discord.Interaction[Any]) -> None:
            await move(interaction, -1)

        async def down(interaction: discord.Interaction[Any]) -> None:
            await move(interaction, 1)

        async def remove(interaction: discord.Interaction[Any]) -> None:
            self.actions.pop(i)
            self.mode = "actions"
            await self.refresh(interaction)

        async def done(interaction: discord.Interaction[Any]) -> None:
            self.mode = "actions"
            await self.refresh(interaction)

        controls: list[ui.Item[Any]] = []
        if texts:
            controls.append(button("Edit texts", self._action_modal(action, kind.name, texts),
                                   style=discord.ButtonStyle.primary))
        controls += toggles
        if controls:
            box.add_item(row(*controls[:5]))
        box.add_item(row(button("Move up", up, disabled=i == 0), button("Move down", down, disabled=i >= len(actions) - 1),
                         button("Remove", remove, style=discord.ButtonStyle.danger),
                         button(f"{Glyph.PREV} All actions", done)))
        return box

    def _action_channel(self, action: dict[str, Any], f: ActionField) -> ui.ChannelSelect[Any]:
        current = action.get(f.key)
        sel: ui.ChannelSelect[Any] = ui.ChannelSelect(
            placeholder=f"{f.label}{' *' if f.required else ''}", min_values=0, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice],
            default_values=[discord.Object(int(current))] if current else [])

        async def cb(interaction: discord.Interaction[Any]) -> None:
            action[f.key] = sel.values[0].id if sel.values else None
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _action_role(self, action: dict[str, Any], f: ActionField) -> ui.RoleSelect[Any]:
        current = action.get(f.key)
        sel: ui.RoleSelect[Any] = ui.RoleSelect(
            placeholder=f"{f.label}{' *' if f.required else ''}", min_values=0, max_values=1,
            default_values=[discord.Object(int(current))] if current else [])

        async def cb(interaction: discord.Interaction[Any]) -> None:
            action[f.key] = sel.values[0].id if sel.values else None
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _action_automation(self, action: dict[str, Any], f: ActionField) -> ui.Select[Any]:
        own = self.existing.hook_id if self.existing else None
        targets = [a for a in self.cog.for_guild(self.guild_id or 0) if a.template == CUSTOM.id and a.hook_id != own]
        options = [discord.SelectOption(label=cards.truncate(a.name, 90), value=a.hook_id, description=a.hook_id,
                                        default=a.hook_id == action.get(f.key)) for a in targets[:25]]
        sel: ui.Select[Any] = ui.Select(
            placeholder=f.label if options else "No other custom automations in this server yet",
            options=options or [discord.SelectOption(label="none", value="none")], disabled=not options)

        async def cb(interaction: discord.Interaction[Any]) -> None:
            action[f.key] = sel.values[0]
            await self.refresh(interaction)

        sel.callback = cb  # type: ignore[method-assign]
        return sel

    def _action_toggle(self, action: dict[str, Any], f: ActionField) -> ui.Button[Any]:
        on = bool(action.get(f.key, f.default))

        async def cb(interaction: discord.Interaction[Any]) -> None:
            action[f.key] = not bool(action.get(f.key, f.default))
            await self.refresh(interaction)

        return button(f"{f.label[:70]}: {'On' if on else 'Off'}", cb,
                      style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary)

    def _action_modal(self, action: dict[str, Any], title: str, fields: list[ActionField]):
        async def cb(interaction: discord.Interaction[Any]) -> None:
            form = []
            for f in fields[:5]:
                value = action.get(f.key)
                text = json.dumps(value, ensure_ascii=False) if f.kind == "json" and value not in (None, "") and \
                    not isinstance(value, str) else value
                form.append(FormField(f.key, f.label, description=cards.truncate(f.description, 100) or None,
                                      default=None if text is None else str(text)[:4000], required=f.required,
                                      paragraph=f.kind in ("textarea", "json"),
                                      max_length=300 if f.kind == "text" else 4000))

            async def done(modal_interaction: discord.Interaction[Any], values: dict[str, str]) -> None:
                self.errors = []
                for f in fields[:5]:
                    if f.key in values:
                        value, err = coerce(f, values[f.key])
                        if err:
                            self.errors.append(err)
                        else:
                            action[f.key] = value
                await self.refresh(modal_interaction)

            await interaction.response.send_modal(FormModal(cards.truncate(title, 45), form, done))

        return cb

    async def _save(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer()
        try:
            self.done = await self.cog.save_automation(
                guild=interaction.guild, template=self.template, name=self.name, config=self.config,
                author_id=interaction.user.id, existing=self.existing)
        except Exception as exc:
            self.errors = [f"Could not save: {cards.truncate(exc, 300)}"]
        await self.refresh(interaction)
        if self.done is not None:
            self.stop()

    async def _cancel(self, interaction: discord.Interaction[Any]) -> None:
        self.clear_items()
        self.add_item(cards.card("Cancelled", "Nothing was saved.", accent="muted"))
        await interaction.response.edit_message(view=self)
        self.stop()
