from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from .model import PickerRequest, portal_request


BUS_NAME = "org.freedesktop.impl.portal.desktop.omarchy.FilePicker"
OBJECT_PATH = "/org/freedesktop/portal/desktop"

FILE_CHOOSER_XML = """
<node>
  <interface name="org.freedesktop.impl.portal.FileChooser">
    <method name="OpenFile">
      <arg type="o" name="handle" direction="in"/>
      <arg type="s" name="app_id" direction="in"/>
      <arg type="s" name="parent_window" direction="in"/>
      <arg type="s" name="title" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="u" name="response" direction="out"/>
      <arg type="a{sv}" name="results" direction="out"/>
    </method>
    <method name="SaveFile">
      <arg type="o" name="handle" direction="in"/>
      <arg type="s" name="app_id" direction="in"/>
      <arg type="s" name="parent_window" direction="in"/>
      <arg type="s" name="title" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="u" name="response" direction="out"/>
      <arg type="a{sv}" name="results" direction="out"/>
    </method>
    <method name="SaveFiles">
      <arg type="o" name="handle" direction="in"/>
      <arg type="s" name="app_id" direction="in"/>
      <arg type="s" name="parent_window" direction="in"/>
      <arg type="s" name="title" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="u" name="response" direction="out"/>
      <arg type="a{sv}" name="results" direction="out"/>
    </method>
  </interface>
</node>
"""

REQUEST_XML = """
<node>
  <interface name="org.freedesktop.impl.portal.Request">
    <method name="Close"/>
  </interface>
</node>
"""


def unpack(value: Any) -> Any:
    if isinstance(value, GLib.Variant):
        return unpack(value.unpack())
    if isinstance(value, dict):
        return {key: unpack(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(unpack(item) for item in value)
    if isinstance(value, list):
        return [unpack(item) for item in value]
    return value


def request_to_json(request: PickerRequest) -> dict[str, Any]:
    payload = asdict(request)
    payload["current_folder"] = str(request.current_folder)
    payload["filters"] = [[item.name, [list(rule) for rule in item.rules]] for item in request.filters]
    return payload


class ActiveRequest:
    def __init__(
        self,
        service: "PortalService",
        method: str,
        handle: str,
        invocation: Gio.DBusMethodInvocation,
        request: PickerRequest,
    ) -> None:
        self.service = service
        self.method = method
        self.handle = handle
        self.invocation = invocation
        self.request = request
        self.tempdir = tempfile.TemporaryDirectory(prefix="omarchy-file-picker-")
        root = Path(self.tempdir.name)
        self.request_path = root / "request.json"
        self.result_path = root / "result.json"
        self.request_path.write_text(json.dumps(request_to_json(request)), encoding="utf-8")
        self.registration_id = service.connection.register_object(
            handle,
            service.request_interface,
            self._handle_request_method,
            None,
            None,
        )
        picker = shutil.which("omarchy-file-picker")
        if not picker:
            picker = str(Path(__file__).resolve().parents[1] / "bin/omarchy-file-picker")
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
        self.process = launcher.spawnv([picker, "--request", str(self.request_path), "--result", str(self.result_path)])
        self.process.wait_async(None, self._on_finished)

    def _handle_request_method(
        self,
        _connection,
        _sender,
        _object_path,
        interface_name,
        method_name,
        _parameters,
        invocation,
    ) -> None:
        if interface_name == "org.freedesktop.impl.portal.Request" and method_name == "Close":
            self.cancel()
            invocation.return_value(None)

    def cancel(self) -> None:
        if self.process:
            self.process.force_exit()
        self.complete(1, {})

    def _on_finished(self, process: Gio.Subprocess, result) -> None:
        try:
            process.wait_finish(result)
        except GLib.Error:
            self.complete(2, {})
            return
        if self.handle not in self.service.requests:
            return
        try:
            payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.complete(2, {})
            return
        if payload.get("response") != "ok":
            self.complete(1, {})
            return

        uris = [str(uri) for uri in payload.get("uris", []) if str(uri).startswith("file://")]
        if self.method == "SaveFiles" and uris:
            folder = Path(GLib.filename_from_uri(uris[0])[0])
            uris = [(folder / name).resolve().as_uri() for name in self.request.files]
        results: dict[str, GLib.Variant] = {
            "uris": GLib.Variant("as", uris),
            "choices": GLib.Variant("a(ss)", list(payload.get("choices", {}).items())),
        }
        current_filter = payload.get("current_filter")
        if current_filter:
            name, rules = current_filter
            results["current_filter"] = GLib.Variant("(sa(us))", (name, [tuple(rule) for rule in rules]))
        if self.method == "OpenFile":
            results["writable"] = GLib.Variant("b", False)
        self.complete(0, results)

    def complete(self, response: int, results: dict[str, GLib.Variant]) -> None:
        if self.handle not in self.service.requests:
            return
        try:
            self.invocation.return_value(GLib.Variant("(ua{sv})", (response, results)))
        finally:
            self.service.connection.unregister_object(self.registration_id)
            self.service.requests.pop(self.handle, None)
            self.tempdir.cleanup()


class PortalService:
    def __init__(self) -> None:
        self.loop = GLib.MainLoop()
        self.connection: Gio.DBusConnection | None = None
        self.object_registration_id = 0
        self.requests: dict[str, ActiveRequest] = {}
        self.file_interface = Gio.DBusNodeInfo.new_for_xml(FILE_CHOOSER_XML).interfaces[0]
        self.request_interface = Gio.DBusNodeInfo.new_for_xml(REQUEST_XML).interfaces[0]
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            self._on_name_lost,
        )

    def _on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self.connection = connection
        self.object_registration_id = connection.register_object(
            OBJECT_PATH,
            self.file_interface,
            self._handle_method,
            None,
            None,
        )

    def _on_name_lost(self, _connection, _name: str) -> None:
        self.loop.quit()

    def _handle_method(
        self,
        _connection,
        _sender,
        _object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ) -> None:
        if interface_name != "org.freedesktop.impl.portal.FileChooser":
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownInterface", interface_name)
            return
        try:
            handle, app_id, _parent_window, title, raw_options = parameters.unpack()
            options = unpack(raw_options)
            request = portal_request(method_name, app_id, title, options)
            active = ActiveRequest(self, method_name, handle, invocation, request)
            self.requests[handle] = active
        except Exception as error:
            invocation.return_dbus_error(
                "org.freedesktop.impl.portal.Error.Failed",
                f"Unable to launch Omarchy File Picker: {error}",
            )

    def run(self) -> int:
        try:
            self.loop.run()
        finally:
            for request in list(self.requests.values()):
                request.cancel()
            Gio.bus_unown_name(self.owner_id)
        return 0


def main() -> int:
    return PortalService().run()


if __name__ == "__main__":
    raise SystemExit(main())
