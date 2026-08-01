"""后台网络请求的调度、回收与结果展示。"""
from __future__ import annotations

import concurrent.futures
import queue
import threading
from tkinter import messagebox

import core
import remote_dialog
from ui import theme


# Batch health checks run concurrently but stay modest: these are third-party gateways,
# and a burst of parallel requests is a good way to get rate-limited.
HEALTH_CHECK_WORKERS = 6
HEALTH_CHECK_TIMEOUT = 10


class NetworkMixin:
    """依赖 App 提供的：_network_busy、_network_results 队列、_health、
    base_url_var、api_key_var、api_var、show_hidden、status_var、provider_tree、
    current_provider、_apply_action_states、_selected_model_id，
    以及 tk 的 after()。"""

    def _set_network_busy(self, busy: bool) -> None:
        self._network_busy = busy
        self._apply_action_states()

    def _run_network(self, status: str, action, on_success) -> None:
        if self._network_busy:
            return
        self._set_network_busy(True)
        self.status_var.set(status)

        def worker() -> None:
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001 - converted to a GUI error on the main thread
                self._network_results.put((None, exc))
            else:
                self._network_results.put((lambda: on_success(result), None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_network_results(self) -> None:
        try:
            while True:
                callback, error = self._network_results.get_nowait()
                self._set_network_busy(False)
                if error is not None:
                    self.status_var.set("连接失败")
                    messagebox.showerror(theme.WINDOW_TITLE, str(error))
                elif callback is not None:
                    callback()
        except queue.Empty:
            pass
        self.after(100, self._poll_network_results)

    def _fetch_action_from_form(self):
        base_url = self.base_url_var.get()
        api_key = self.api_key_var.get()
        return lambda: core.fetch_remote_models(base_url, api_key, timeout=20)

    def test_connection(self) -> None:
        """List models, then send one real 1-token completion.

        A proxy that answers /v1/models can still reject real completions — that gap is
        why backfill_proxy_compat exists, and listing alone never revealed it.
        """
        base_url = self.base_url_var.get()
        api_key = self.api_key_var.get()
        api = self.api_var.get()
        preferred = self._selected_model_id()

        def action():
            models = core.fetch_remote_models(base_url, api_key, timeout=20)
            if not core.supports_chat_probe(api):
                return (models, None, f"{api} 不支持对话探测，仅验证了模型接口。")
            probe_model = preferred or (models[0]["id"] if models else "")
            if not probe_model:
                return (models, None, "接口未返回模型，无法进行对话探测。")
            try:
                core.probe_chat(base_url, api, probe_model, api_key, timeout=20)
            except ValueError as exc:
                return (models, False, f"对话失败（{probe_model}）：{exc}")
            return (models, True, f"对话正常（{probe_model}）。")

        def success(result) -> None:
            models, chat_ok, note = result
            if chat_ok is False:
                self.status_var.set("模型接口可用，但对话失败")
                messagebox.showwarning(
                    theme.WINDOW_TITLE,
                    f"模型接口可用，共 {len(models)} 个模型。\n\n{note}",
                )
                return
            self.status_var.set(f"连接成功，发现 {len(models)} 个模型")
            messagebox.showinfo(
                theme.WINDOW_TITLE, f"共发现 {len(models)} 个模型。\n{note}"
            )

        self._run_network("正在测试模型接口与对话...", action, success)

    def check_all_providers(self) -> None:
        """Health-check every listed provider using the free /v1/models endpoint.

        Deliberately shallow: a real completion costs tokens, so that stays on
        测试连接 for one provider at a time. Results are display-only — nothing is written.
        """
        custom = core.load_custom()
        auth = core.load_auth()
        store = core.load_models_store()
        custom_providers = custom["providers"]
        targets = [
            (provider, cfg) for provider, cfg in sorted(custom_providers.items())
            if isinstance(cfg, dict)
        ]
        hidden = set() if self.show_hidden.get() else core.load_hidden_builtins()
        for provider, info in sorted(store.items()):
            if provider in custom_providers or not isinstance(info, dict):
                continue
            if provider in hidden:
                continue
            targets.append((provider, info))
        if not targets:
            messagebox.showinfo(theme.WINDOW_TITLE, "没有可检查的供应商。")
            return

        def action():
            with concurrent.futures.ThreadPoolExecutor(max_workers=HEALTH_CHECK_WORKERS) as pool:
                return list(pool.map(
                    lambda item: core.probe_provider(
                        item[0], item[1], auth, timeout=HEALTH_CHECK_TIMEOUT,
                    ),
                    targets,
                ))

        self._run_network(
            f"正在检查 {len(targets)} 个供应商...",
            action,
            self._show_health_results,
        )

    def _show_health_results(self, results: list[dict]) -> None:
        ok_count = 0
        for result in results:
            provider = result.get("provider")
            if result.get("ok"):
                ok_count += 1
                cell = f"{result.get('latency_ms', 0)} ms"
            else:
                cell = "失败"
            self._health[provider] = cell
        failed = [r for r in results if not r.get("ok")]
        self.refresh_providers(select=self.current_provider, load_selection=False)
        self.status_var.set(f"检查完成：{ok_count} 通过，{len(failed)} 失败")
        if failed:
            lines = "\n".join(f"{r['provider']}：{r['detail']}" for r in failed[:12])
            if len(failed) > 12:
                lines += f"\n... 共 {len(failed)} 个失败"
            messagebox.showwarning(theme.WINDOW_TITLE, lines)

    def fetch_models(self) -> None:
        if not self.current_provider:
            messagebox.showinfo(theme.WINDOW_TITLE, "请先保存供应商")
            return
        provider = self.current_provider
        self._run_network(
            "正在拉取模型列表...",
            self._fetch_action_from_form(),
            lambda models: self._show_remote_models(models, provider),
        )

    def _show_remote_models(self, models: list[dict], provider: str) -> None:
        remote_dialog.show_remote_models(self, models, provider)
