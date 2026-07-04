# Local Network LaunchServices Repair Compatibility

`refresh-launchservices-user-cache` must not call `lsregister -kill`.

Recent macOS releases reject that option with:

```text
The -kill option has been removed because it was dangerous and no longer useful.
```

The Local Network repair action is limited to derived LaunchServices/user registration refresh behavior. It must not delete applications, Chrome profiles, TCC databases, user documents, arbitrary LaunchServices files, or the LaunchServices database.

The supported refresh path is:

```text
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -r -f -apps user
```

Preflight is intentionally conservative and local: it validates that the action is still wired to exactly the supported command form above and that no removed or destructive options (`-kill`, `-delete`, `-u`) are present. It must not depend on brittle `lsregister -h` output, because supported macOS versions may fail or localize help output differently.

If the executable exists and the command form is safe, the repair should attempt the supported refresh. Any macOS-level option rejection from that execution is then reported with stderr plus fallback guidance instead of blocking before execution.
