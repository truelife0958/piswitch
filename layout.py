"""Widget construction for the main window.

Separated from App so the behaviour methods read as behaviour: this module only creates
widgets and attaches them to `app`, and holds no logic of its own.
"""
from __future__ import annotations

from tkinter import ttk

import core


def build(app) -> None:
    toolbar = ttk.Frame(app, padding=(10, 8))
    toolbar.pack(fill="x")
    ttk.Label(toolbar, text="自定义模型供应商", font=("TkDefaultFont", 13, "bold")).pack(side="left")
    ttk.Button(toolbar, text="新增", command=app.new_provider).pack(side="right", padx=(6, 0))
    ttk.Checkbutton(toolbar, text="显示隐藏", variable=app.show_hidden, command=app.refresh_providers).pack(side="right", padx=(6, 0))
    ttk.Button(toolbar, text="刷新", command=app.refresh_providers).pack(side="right")
    app.check_all_button = ttk.Button(toolbar, text="检查全部", command=app.check_all_providers)
    app.check_all_button.pack(side="right", padx=6)
    ttk.Button(toolbar, text="恢复备份", command=app.open_backup_restore).pack(side="right", padx=6)
    ttk.Button(toolbar, text="导入", command=app.import_config).pack(side="right")
    ttk.Button(toolbar, text="导出", command=app.export_config).pack(side="right", padx=6)

    pane = ttk.PanedWindow(app, orient="horizontal")
    pane.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    left = ttk.Frame(pane, padding=(0, 4, 8, 4))
    right = ttk.Frame(pane, padding=(8, 4, 0, 4))
    pane.add(left, weight=2)
    pane.add(right, weight=3)

    app.provider_tree = ttk.Treeview(
        left,
        columns=("provider", "name", "models", "auth", "health"),
        show="headings",
        selectmode="browse",
    )
    headings = (
        ("provider", "Provider ID", 112),
        ("name", "名称", 86),
        ("models", "模型", 40),
        ("auth", "验证", 54),
        ("health", "状态", 48),
    )
    for column, title, width in headings:
        app.provider_tree.heading(column, text=title)
        app.provider_tree.column(column, width=width, minwidth=40, anchor="w")
    provider_scroll = ttk.Scrollbar(left, orient="vertical", command=app.provider_tree.yview)
    app.provider_tree.configure(yscrollcommand=provider_scroll.set)
    # Scrollbar first: pack gives the expanding tree every remaining pixel, so a
    # scrollbar packed after it is allotted nothing and never gets mapped.
    provider_scroll.pack(side="right", fill="y")
    app.provider_tree.pack(side="left", fill="both", expand=True)
    app.provider_tree.bind("<<TreeviewSelect>>", app._on_provider_selected)

    form = ttk.Frame(right)
    form.pack(fill="x")
    form.columnconfigure(1, weight=1)
    fields = (
        ("Provider ID", app.provider_var),
        ("显示名称", app.name_var),
        ("Base URL", app.base_url_var),
    )
    for row, (label, variable) in enumerate(fields):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ttk.Entry(form, textvariable=variable)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        if row == 0:
            app.provider_entry = entry

    ttk.Label(form, text="API 类型").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=5)
    ttk.Combobox(form, textvariable=app.api_var, values=core.API_TYPES, state="readonly").grid(
        row=3, column=1, columnspan=2, sticky="ew", pady=5
    )

    ttk.Label(form, text="API Key").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=5)
    app.api_key_entry = ttk.Entry(form, textvariable=app.api_key_var, show="*")
    app.api_key_entry.grid(row=4, column=1, sticky="ew", pady=5)
    ttk.Checkbutton(
        form,
        text="显示",
        variable=app.show_key_var,
        command=app._toggle_key_visibility,
    ).grid(row=4, column=2, sticky="e", padx=(8, 0))
    app.key_status_label = ttk.Label(form, textvariable=app.key_status_var, anchor="w")
    app.key_status_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(0, 2))

    actions = ttk.Frame(right)
    actions.pack(fill="x", pady=(10, 14))
    app.save_provider_button = ttk.Button(actions, text="保存供应商", command=app.save_provider)
    app.save_provider_button.pack(side="left")
    app.test_connection_button = ttk.Button(actions, text="测试连接", command=app.test_connection)
    app.test_connection_button.pack(side="left", padx=(8, 0))
    app.delete_provider_button = ttk.Button(actions, text="删除供应商", command=app.delete_provider)
    app.delete_provider_button.pack(side="left", padx=8)
    app.logout_provider_button = ttk.Button(actions, text="退出登录", command=app.logout_provider)
    app.logout_provider_button.pack(side="left", padx=8)
    app.hide_builtin_button = ttk.Button(actions, text="从列表移除", command=app.toggle_hide_builtin)
    app.hide_builtin_button.pack(side="left", padx=8)
    app._action_buttons = {
        "save": app.save_provider_button,
        "test": app.test_connection_button,
        "delete_provider": app.delete_provider_button,
        "logout": app.logout_provider_button,
        "hide_builtin": app.hide_builtin_button,
    }

    model_header = ttk.Frame(right)
    model_header.pack(fill="x", pady=(2, 6))
    ttk.Label(model_header, text="模型", font=("TkDefaultFont", 11, "bold")).pack(side="left")
    app.set_default_button = ttk.Button(model_header, text="设为默认", command=app.set_default)
    app.set_default_button.pack(side="left", padx=(10, 0))
    app.clear_models_button = ttk.Button(model_header, text="清空", command=app.clear_models)
    app.clear_models_button.pack(side="right")
    app.delete_model_button = ttk.Button(model_header, text="删除模型", command=app.delete_model)
    app.delete_model_button.pack(side="right", padx=6)
    app.add_model_button = ttk.Button(model_header, text="增加模型", command=app.add_models)
    app.add_model_button.pack(side="right", padx=6)
    app.fetch_model_button = ttk.Button(model_header, text="拉取模型", command=app.fetch_models)
    app.fetch_model_button.pack(side="right")
    app._action_buttons.update({
        "add_model": app.add_model_button,
        "delete_model": app.delete_model_button,
        "clear_models": app.clear_models_button,
        "fetch_models": app.fetch_model_button,
        "set_default": app.set_default_button,
    })

    model_area = ttk.Frame(right)
    model_area.pack(fill="both", expand=True)
    app.model_tree = ttk.Treeview(
        model_area,
        columns=("default", "id", "name", "context", "reasoning"),
        show="headings",
        selectmode="extended",
    )
    for column, title, width in (
        ("default", "默认", 38),
        ("id", "Model ID", 188),
        ("name", "名称", 118),
        ("context", "上下文", 72),
        ("reasoning", "推理", 44),
    ):
        app.model_tree.heading(column, text=title)
        app.model_tree.column(column, width=width, minwidth=40, anchor="w")
    app.model_tree.column("default", anchor="center", stretch=False)
    model_scroll = ttk.Scrollbar(model_area, orient="vertical", command=app.model_tree.yview)
    app.model_tree.configure(yscrollcommand=model_scroll.set)
    model_scroll.pack(side="right", fill="y")
    app.model_tree.pack(side="left", fill="both", expand=True)
    # Double-click a model row to point pi at it.
    app.model_tree.bind("<Double-Button-1>", app._on_model_double_click)

    ttk.Label(app, textvariable=app.status_var, anchor="w", relief="sunken", padding=(8, 4)).pack(fill="x")
