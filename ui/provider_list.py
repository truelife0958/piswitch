"""供应商列表的渲染、选中与只读态。"""
from __future__ import annotations

import core


OAUTH_LABELS = {"logged_in": "(OAuth，已登录)", "expired": "(OAuth，已过期)"}


class ProviderListMixin:
    """依赖 App 提供的：provider_tree、provider_filter_var、provider_count_var、
    show_hidden、status_var、key_status_var、表单五个 StringVar 与 show_key_var、
    provider_entry/name_entry/base_url_entry/api_combo/api_key_entry/key_visibility_check、
    _action_buttons、_menu_actions、provider_actions_menu、provider_more_button、
    model_more_button、check_all_button、_provider_records、_health、_network_busy、
    current_provider、_current_is_builtin、_current_has_oauth、_current_is_hidden、
    _current_config、_tracking_form、_confirm_form_transition、_restore_provider_selection、
    _toggle_key_visibility、_mark_form_clean、_refresh_models、_reset_new_provider_form。"""

    def _render_provider_rows(self, select: str | None = None) -> None:
        query = self.provider_filter_var.get()
        self.provider_tree.delete(*self.provider_tree.get_children())
        for record in self._provider_records:
            if not core.text_matches_query(query, *record["values"]):
                continue
            self.provider_tree.insert(
                "", "end", iid=record["provider"], values=record["values"]
            )
        visible = len(self.provider_tree.get_children())
        total = len(self._provider_records)
        self.provider_count_var.set(
            f"{visible}/{total}" if query.strip() else f"{total} 个"
        )
        if select and self.provider_tree.exists(select):
            self.provider_tree.selection_set(select)
            self.provider_tree.focus(select)
            self.provider_tree.see(select)

    def refresh_providers(
        self, select: str | None = None, *, load_selection: bool = True
    ) -> None:
        snap = core.load_snapshot()
        hidden = set() if self.show_hidden.get() else snap.hidden
        records = core.provider_rows(
            snap.custom, snap.auth, snap.store,
            default_provider=snap.settings.get("defaultProvider"),
            health=self._health, hidden=hidden,
        )
        self._provider_records = records
        target = select or self.current_provider
        self._render_provider_rows(select=target)
        if target and self.provider_tree.exists(target):
            if load_selection:
                self._load_provider(target, snap=snap)
        elif load_selection and not self.provider_tree.get_children():
            if not self.provider_filter_var.get().strip():
                self._reset_new_provider_form()
        elif load_selection:
            first = self.provider_tree.get_children()[0]
            self.provider_tree.selection_set(first)
            self.provider_tree.focus(first)
            self._load_provider(first, snap=snap)
        # 列表里也有内置，所以两个数都报，而不是只报自定义的
        custom_count = sum(1 for record in records if record["custom"])
        self.status_var.set(
            f"已加载 {custom_count} 个自定义供应商，{len(records) - custom_count} 个内置"
        )

    def _on_provider_selected(self, _event=None) -> None:
        selection = self.provider_tree.selection()
        if selection:
            target = selection[0]
            if target == self.current_provider:
                return
            if not self._confirm_form_transition():
                self._restore_provider_selection()
                return
            self._load_provider(target)

    def _load_provider(self, provider: str, *, snap: core.Snapshot | None = None) -> None:
        snap = snap or core.load_snapshot()
        custom, auth, store = snap.custom, snap.auth, snap.store
        config = custom["providers"].get(provider)
        builtin = core.is_builtin_provider(provider, store)
        if not isinstance(config, dict):
            # not custom — fall back to the builtin store entry (read-only)
            if not builtin:
                return
            config = store.get(provider, {})

        auth_entry = auth.get(provider)
        kind = core.auth_kind(provider, auth, custom)
        self.current_provider = provider
        self._current_is_builtin = builtin
        # Logout / delete-credentials needs an actual OAuth entry to clear.
        self._current_has_oauth = (
            kind == "oauth" and isinstance(auth_entry, dict) and bool(auth_entry)
        )
        self._current_is_hidden = builtin and provider in snap.hidden

        self._tracking_form = False
        try:
            self.provider_var.set(provider)
            self.name_var.set(config.get("name") or provider)
            self.base_url_var.set(config.get("baseUrl", ""))
            self.api_var.set(config.get("api", core.API_TYPES[0]))
            if kind == "oauth":
                # OAuth access tokens are extension-managed; show read-only status instead.
                self.api_key_var.set(
                    OAUTH_LABELS.get(core.auth_login_state(provider, auth), "(OAuth)")
                )
            elif kind == "api_key":
                auth_key = auth_entry.get("key") if isinstance(auth_entry, dict) else ""
                self.api_key_var.set(auth_key or config.get("apiKey", ""))
            else:
                self.api_key_var.set(config.get("apiKey", ""))

            # Builtin providers are read-only: label missing store-owned values clearly.
            if builtin:
                self.name_var.set(config.get("name") or f"{provider} (内置)")
                self.base_url_var.set(config.get("baseUrl") or "(内置)")
            self.show_key_var.set(False)
            self._toggle_key_visibility()
        finally:
            self._tracking_form = True

        field_state = "disabled" if builtin else "normal"
        self.provider_entry.configure(state=field_state)
        self.name_entry.configure(state=field_state)
        self.base_url_entry.configure(state=field_state)
        self.api_combo.configure(state="disabled" if builtin else "readonly")
        key_editable = not builtin and kind != "oauth"
        self.api_key_entry.configure(state="normal" if key_editable else "disabled")
        self.key_visibility_check.configure(state="normal" if key_editable else "disabled")
        self._current_config = config
        self._apply_action_states()
        self._refresh_models(config, settings=snap.settings)
        self._mark_form_clean()

    def _apply_action_states(self) -> None:
        """Push the derived enable/disable state onto every action button.

        Sole writer of action-button state: selection changes and network transitions both
        route through here, so they cannot leave contradictory states behind.
        """
        states = core.action_states(
            busy=self._network_busy,
            selected=bool(self.current_provider),
            builtin=self._current_is_builtin,
            has_oauth=self._current_has_oauth,
        )
        for key, enabled in states.items():
            state = "normal" if enabled else "disabled"
            button = self._action_buttons.get(key)
            if button is not None:
                button.configure(state=state)
            elif key in self._menu_actions:
                menu, index = self._menu_actions[key]
                menu.entryconfigure(index, state=state)
        self.provider_actions_menu.entryconfigure(
            self._menu_actions["hide_builtin"][1],
            label="恢复显示" if self._current_is_hidden else "从列表移除",
        )
        self.provider_more_button.configure(
            state="normal" if any(
                states[key] for key in ("delete_provider", "logout", "hide_builtin")
            ) else "disabled"
        )
        self.model_more_button.configure(
            state="normal" if any(
                states[key] for key in ("add_model", "delete_model", "clear_models")
            ) else "disabled"
        )
        # Batch check depends only on the network being idle, not on any selection.
        self.check_all_button.configure(state="disabled" if self._network_busy else "normal")

    def _refresh_key_status(self) -> None:
        """Show whether a `$ENV_VAR` key would actually resolve, without waiting for a request."""
        state, variable = core.api_key_status(self.api_key_var.get())
        self.key_status_var.set({
            "env_set": f"✓ ${variable} 已设置",
            "env_missing": f"✗ ${variable} 未设置",
            "invalid": "✗ $ 后缺少变量名",
        }.get(state, ""))

    def toggle_show_hidden(self) -> None:
        # This only changes which rows are visible; the current form remains untouched.
        self.refresh_providers(load_selection=False)

    def _on_provider_filter_changed(self, *_args) -> None:
        self._render_provider_rows(select=self.current_provider)
