"""Freedesktop file-manager D-Bus service backed by Gudfiles."""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from gi.repository import Gio, GLib

BUS_NAME = "org.freedesktop.FileManager1"
OBJECT_PATH = "/org/freedesktop/FileManager1"
INTERFACE = BUS_NAME

FILE_MANAGER_XML = """
<node>
  <interface name="org.freedesktop.FileManager1">
    <method name="ShowFolders">
      <arg name="URIs" type="as" direction="in"/>
      <arg name="StartupId" type="s" direction="in"/>
    </method>
    <method name="ShowItems">
      <arg name="URIs" type="as" direction="in"/>
      <arg name="StartupId" type="s" direction="in"/>
    </method>
    <method name="ShowItemProperties">
      <arg name="URIs" type="as" direction="in"/>
      <arg name="StartupId" type="s" direction="in"/>
    </method>
  </interface>
</node>
"""


def paths_for_show_request(uris: list[str]) -> list[Path]:
    paths = []
    for uri in uris:
        parsed = urlparse(uri)
        if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
            path = Path(unquote(parsed.path))
            if path.is_absolute() and '\0' not in str(path) and path not in paths:
                paths.append(path)
    return paths


def path_for_show_request(uris: list[str]) -> Path | None:
    return next(iter(paths_for_show_request(uris)), None)


def show_request_commands(launcher: str, method: str, uris: list[str]) -> list[list[str]]:
    groups: dict[Path, list[Path]] = {}
    for path in paths_for_show_request(uris):
        folder = path if method == 'ShowFolders' else path.parent
        groups.setdefault(folder, []).append(path)
    commands = []
    for folder, targets in groups.items():
        command = [launcher, '--external', '--demo', str(folder), '--multiple']
        if method != 'ShowFolders':
            for target in targets:
                command.extend(['--select', str(target)])
        commands.append(command)
    return commands


class FileManagerService:
    def __init__(self, launcher: str | None = None) -> None:
        self.launcher = launcher or shutil.which("gudfiles") or shutil.which("omarchy-file-picker")
        if not self.launcher:
            raise RuntimeError("Gudfiles launcher is unavailable")
        self.loop = GLib.MainLoop()
        self.connection: Gio.DBusConnection | None = None
        self.registration_id = 0
        self.interface = Gio.DBusNodeInfo.new_for_xml(FILE_MANAGER_XML).interfaces[0]
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
        self.registration_id = connection.register_object(
            OBJECT_PATH, self.interface, self._handle_method, None, None
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
        if interface_name != INTERFACE or method_name not in {
            "ShowFolders", "ShowItems", "ShowItemProperties"
        }:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method_name)
            return
        uris, _startup_id = parameters.unpack()
        try:
            for command in show_request_commands(self.launcher, method_name, list(uris)):
                Gio.Subprocess.new(
                    command,
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
        except GLib.Error as error:
            invocation.return_dbus_error('org.freedesktop.DBus.Error.Failed', str(error))
            return
        invocation.return_value(None)

    def run(self) -> int:
        try:
            self.loop.run()
        finally:
            if self.connection and self.registration_id:
                self.connection.unregister_object(self.registration_id)
            Gio.bus_unown_name(self.owner_id)
        return 0


def main() -> int:
    return FileManagerService().run()


if __name__ == "__main__":
    raise SystemExit(main())
